from datetime import datetime
import json
from uuid import UUID

import httpx
import pytest

from app.routes import publish as publish_route
from models.channel import Channel
from models.channel_content import ChannelContent
from models.post import Post

from services.publisher.publisher_service import PublisherService
from services.publisher.adapters.mock import MockPublisher
from services.publisher.adapters.telegram import TelegramPublisher
from services.publisher.media import PublicationMedia
from services.publisher.models import PublishResult


def persist_content(db, platform="web"):
    channel = Channel(id=1, name="News", platform=platform, language_code="ru",
                      gateway_channel_id="editorial-news")
    post = Post(id=2, title="Title", topic="Topic", ru_content="Русский текст", en_content="EN")
    content = make_content()
    db.add_all([channel, post, content])
    db.commit()
    return content


def test_mock_publish(isolated_db):
    content = persist_content(isolated_db)
    result = PublisherService(db=isolated_db, publisher=MockPublisher()).publish(content)
    assert result.success is True
    assert content.status == "published"
    assert content.platform_post_id.startswith("mock_")
    assert isinstance(content.published_at, datetime)


def gateway_success(message_id=101):
    return {"status": "published", "provider": "telegram",
            "channel_id": "editorial-news", "external_message_id": message_id}


def make_content(content_id=42):
    return ChannelContent(
        id=content_id,
        channel_id=1,
        post_id=2,
        status="pending",
    )


def make_gateway_publisher(
    handler, content_id=42, text="Publication", media=None
):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return TelegramPublisher(
        gateway_url="https://gateway.example/base/",
        internal_token="internal-secret",
        gateway_channel_id="editorial-news",
        text=text,
        media=media,
        client=client,
    ), make_content(content_id)


def test_telegram_gateway_success_and_request_contract():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "status": "published",
                "provider": "telegram",
                "channel_id": "editorial-news",
                "external_message_id": 987,
            },
        )

    publisher, content = make_gateway_publisher(handler)
    result = publisher.publish(content)

    assert result.success is True
    assert result.platform_post_id == "987"
    assert requests[0].url == httpx.URL(
        "https://gateway.example/base/api/v1/telegram/publications"
    )
    assert requests[0].headers["Authorization"] == "Bearer internal-secret"
    UUID(requests[0].headers["Idempotency-Key"])
    UUID(requests[0].headers["X-Request-ID"])
    assert json.loads(requests[0].content) == {
        "gateway_channel_id": "editorial-news",
        "text": "<b>Publication</b>",
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }


def test_telegram_gateway_leaves_short_text_unchanged():
    requests = []
    text = "A short publication \U0001f44d"

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=gateway_success())

    publisher, content = make_gateway_publisher(handler, text=text)
    publisher.publish(content)

    assert json.loads(requests[0].content)["text"] == f"<b>{text}</b>"


def test_telegram_gateway_keeps_text_only_limit_above_caption_limit():
    requests = []
    text = "x" * 2000

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=gateway_success())

    publisher, content = make_gateway_publisher(handler, text=text)
    publisher.publish(content)
    payload = json.loads(requests[0].content)

    assert payload["text"] == f"<b>{text}</b>"
    assert "media" not in payload


def test_telegram_gateway_sends_image_and_uses_caption_limit():
    requests = []
    text = "Illustration\n\n" + "🙂" * 350
    media = PublicationMedia(
        asset_id=73,
        type="image",
        url="https://cdn.example/publication.png",
    )

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=gateway_success())

    publisher, content = make_gateway_publisher(handler, text=text, media=media)
    publisher.publish(content)
    payload = json.loads(requests[0].content)

    assert payload["media"] == {
        "type": "image",
        "url": "https://cdn.example/publication.png",
    }
    assert "asset_id" not in payload["media"]
    assert payload["text"] == "<b>Illustration</b>\n\n" + "🙂" * 350
    assert len(payload["text"]) <= 1024


@pytest.mark.parametrize("text", ["First paragraph\n" + "x" * 4096, "🙂" * 5000])
def test_telegram_gateway_rejects_overlong_text_without_sending(text):
    requests = []
    publisher, content = make_gateway_publisher(lambda request: requests.append(request), text=text)
    result = publisher.publish(content)
    assert result.success is False and result.outcome == "failed"
    assert result.error_code == "publication_not_ready"
    assert requests == []
    assert publisher.text == text


def test_telegram_gateway_reuses_idempotency_key_for_repeat_request():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=gateway_success())

    publisher, content = make_gateway_publisher(handler)
    first = publisher.publish(content)
    second = publisher.publish(content)

    assert first.success and second.success
    assert (
        requests[0].headers["Idempotency-Key"] == requests[1].headers["Idempotency-Key"]
    )
    assert requests[0].headers["X-Request-ID"] != requests[1].headers["X-Request-ID"]


@pytest.mark.parametrize("status_code", [400, 401, 403, 409, 422, 500, 502, 503])
def test_telegram_gateway_maps_http_errors(status_code):
    publisher, content = make_gateway_publisher(
        lambda request: httpx.Response(status_code, json={"detail": "redacted"})
    )

    result = publisher.publish(content)

    assert result.success is False
    assert result.error == (
        f'AI Gateway returned HTTP {status_code}: {{"detail": "redacted"}}'
    )


def test_telegram_gateway_exposes_validation_error_body():
    validation_details = {
        "detail": [
            {
                "type": "missing",
                "loc": ["body", "gateway_channel_id"],
                "msg": "Field required",
            }
        ]
    }
    publisher, content = make_gateway_publisher(
        lambda request: httpx.Response(422, json=validation_details)
    )

    result = publisher.publish(content)

    assert result.success is False
    assert result.error == (
        "AI Gateway returned HTTP 422: " + json.dumps(validation_details)
    )


def test_telegram_gateway_falls_back_to_text_error_body():
    publisher, content = make_gateway_publisher(
        lambda request: httpx.Response(502, text="upstream unavailable")
    )

    result = publisher.publish(content)

    assert result.success is False
    assert result.error == "AI Gateway returned HTTP 502: upstream unavailable"


def test_telegram_gateway_preserves_retry_after_for_rate_limit():
    publisher, content = make_gateway_publisher(
        lambda request: httpx.Response(
            429,
            headers={"Retry-After": "30"},
            json={"detail": "slow down"},
        )
    )

    result = publisher.publish(content)

    assert result.success is False
    assert result.error == (
        'AI Gateway returned HTTP 429: {"detail": "slow down"} (Retry-After: 30)'
    )


@pytest.mark.parametrize(
    ("exception", "expected_error"),
    [
        (httpx.ReadTimeout("timed out"), "AI Gateway delivery outcome is unknown after a transport failure"),
        (httpx.ConnectError("dns failed"), "AI Gateway connection was not established"),
    ],
)
def test_telegram_gateway_maps_transport_errors(exception, expected_error):
    def handler(request):
        raise exception

    publisher, content = make_gateway_publisher(handler)

    result = publisher.publish(content)

    assert result.success is False
    assert result.error == expected_error


def test_telegram_gateway_rejects_invalid_json():
    publisher, content = make_gateway_publisher(
        lambda request: httpx.Response(200, content=b"not-json")
    )

    result = publisher.publish(content)

    assert result.success is False
    assert result.error == "AI Gateway returned an invalid publication response"


def test_telegram_gateway_requires_external_message_id():
    publisher, content = make_gateway_publisher(
        lambda request: httpx.Response(200, json={"status": "published"})
    )

    result = publisher.publish(content)

    assert result.success is False
    assert result.error == "AI Gateway returned an invalid publication response"


def test_publish_endpoint_selects_gateway_for_telegram(monkeypatch, isolated_db):
    content = make_content()
    channel = Channel(
        id=1,
        name="News",
        platform="telegram",
        language_code="ru",
        gateway_channel_id="editorial-news",
    )
    post = Post(
        id=2,
        title="Title",
        topic="Topic",
        ru_content="Русский текст",
        en_content="English text",
    )
    captured = {}

    class FakeTelegramPublisher:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def publish(self, published_content):
            assert not isolated_db.in_transaction()
            assert isolated_db.get_bind().pool.checkedout() == 0
            return PublishResult(success=True, platform_post_id="123")

    monkeypatch.setattr(publish_route, "TelegramPublisher", FakeTelegramPublisher)
    monkeypatch.setattr(
        publish_route.settings, "ai_gateway_url", "https://gateway.example"
    )
    monkeypatch.setattr(
        publish_route.settings, "ai_gateway_internal_token", "internal-secret"
    )

    isolated_db.add_all([channel, post, content])
    isolated_db.commit()
    content_id = content.id
    isolated_db.rollback()
    response = publish_route.publish(content_id=content_id, db=isolated_db)

    assert response["platform_post_id"] == "123"
    assert captured == {
        "gateway_url": "https://gateway.example",
        "internal_token": "internal-secret",
        "gateway_channel_id": "editorial-news",
        "text": "Русский текст",
        "media": None,
        "timeout": 30,
    }


def test_publish_endpoint_keeps_mock_for_non_telegram(isolated_db):
    content = persist_content(isolated_db)
    content_id = content.id
    isolated_db.rollback()
    response = publish_route.publish(content_id=content_id, db=isolated_db)
    assert response["platform_post_id"] == "mock_42"


@pytest.mark.parametrize("text", ["Новость\nРусский текст", "News\nEnglish text"])
def test_telegram_caption_preserves_and_escapes_full_image_credit(text):
    credit = "Source: Google & <Artist>. https://official.example/image?a=1&b=2"
    media = PublicationMedia(
        asset_id=73, type="image", url="https://cdn.example/image.jpg", credit=credit
    )
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=gateway_success())

    publisher, content = make_gateway_publisher(handler, text=text, media=media)
    result = publisher.publish(content)
    payload = json.loads(requests[0].content)
    assert result.success
    assert payload["text"].endswith(
        "Source: Google &amp; &lt;Artist&gt;. https://official.example/image?a=1&amp;b=2"
    )
    assert payload["media"] == {"type": "image", "url": media.url}
    assert "credit" not in payload  # Existing Gateway contract, no new fields.


@pytest.mark.parametrize(
    "text,credit",
    [
        ("N" * 1000, "Source: Google. " + "x" * 100),
        ("N" * 900, "🙂" * 70),  # UTF-16 exceeds 1024 while Python/HTML length fits.
    ],
)
def test_overlong_credit_rejects_publication_without_any_request(text, credit):
    requests = []
    media = PublicationMedia(
        asset_id=73, type="image", url="https://cdn.example/image.jpg", credit=credit
    )
    publisher, content = make_gateway_publisher(
        lambda request: requests.append(request), text=text, media=media
    )
    result = publisher.publish(content)
    assert not result.success
    assert result.error_code == "publication_not_ready"
    assert requests == []
    assert publisher.media.credit == credit


def test_caption_at_exact_budget_keeps_complete_credit():
    credit = "Source: Google."
    text = "x" * (1024 - len("<b></b>") - 2 - len(credit))
    rendered = TelegramPublisher.render_html(text, 1024, credit=credit)
    assert len(rendered) == 1024
    assert rendered.endswith("\n\n" + credit)
    with pytest.raises(ValueError):
        TelegramPublisher.render_html(text + "x", 1024, credit=credit)
