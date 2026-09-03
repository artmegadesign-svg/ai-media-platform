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
from services.publisher.models import PublishResult


class FakeSession:
    def commit(self):
        pass

    def refresh(self, obj):
        pass


def test_mock_publish():

    content = ChannelContent(
        channel_id=1,
        post_id=1,
        status="pending",
    )

    service = PublisherService(
        db=FakeSession(),
        publisher=MockPublisher(),
    )

    result = service.publish(content)

    assert result.success is True
    assert content.status == "published"
    assert content.platform_post_id.startswith("mock_")
    assert isinstance(content.published_at, datetime)


def make_content(content_id=42):
    return ChannelContent(
        id=content_id,
        channel_id=1,
        post_id=2,
        status="pending",
    )


def make_gateway_publisher(handler, content_id=42, text="<b>Publication</b>"):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return TelegramPublisher(
        gateway_url="https://gateway.example/base/",
        internal_token="internal-secret",
        gateway_channel_id="editorial-news",
        text=text,
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
        return httpx.Response(200, json={"external_message_id": "101"})

    publisher, content = make_gateway_publisher(handler, text=text)
    publisher.publish(content)

    assert json.loads(requests[0].content)["text"] == text


def test_telegram_gateway_truncates_long_text_at_newline():
    requests = []
    text = "First paragraph\n" + "x" * 4096

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"external_message_id": "101"})

    publisher, content = make_gateway_publisher(handler, text=text)
    publisher.publish(content)
    sent_text = json.loads(requests[0].content)["text"]

    assert sent_text == "First paragraph\n\n…"
    assert len(sent_text) <= 4096


def test_telegram_gateway_truncates_unicode_text_safely():
    requests = []
    text = "🙂" * 5000

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"external_message_id": "101"})

    publisher, content = make_gateway_publisher(handler, text=text)
    publisher.publish(content)
    sent_text = json.loads(requests[0].content)["text"]

    assert sent_text == "🙂" * 4093 + "\n\n…"
    assert len(sent_text) == 4096


def test_telegram_gateway_reuses_idempotency_key_for_repeat_request():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"external_message_id": "101"})

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
        (httpx.ReadTimeout("timed out"), "AI Gateway request timed out"),
        (httpx.ConnectError("dns failed"), "AI Gateway transport error"),
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
    assert result.error == "AI Gateway returned invalid JSON"


def test_telegram_gateway_requires_external_message_id():
    publisher, content = make_gateway_publisher(
        lambda request: httpx.Response(200, json={"status": "published"})
    )

    result = publisher.publish(content)

    assert result.success is False
    assert result.error == "AI Gateway response has no external_message_id"


class QueryResult:
    def __init__(self, value):
        self.value = value

    def filter(self, *args):
        return self

    def first(self):
        return self.value


class RouteSession(FakeSession):
    def __init__(self, values):
        self.values = iter(values)

    def query(self, model):
        return QueryResult(next(self.values))


def test_publish_endpoint_selects_gateway_for_telegram(monkeypatch):
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
            return PublishResult(success=True, platform_post_id="123")

    monkeypatch.setattr(publish_route, "TelegramPublisher", FakeTelegramPublisher)
    monkeypatch.setattr(
        publish_route.settings, "ai_gateway_url", "https://gateway.example"
    )
    monkeypatch.setattr(
        publish_route.settings, "ai_gateway_internal_token", "internal-secret"
    )

    response = publish_route.publish(
        content_id=content.id,
        db=RouteSession([content, channel, post]),
    )

    assert response["platform_post_id"] == "123"
    assert captured == {
        "gateway_url": "https://gateway.example",
        "internal_token": "internal-secret",
        "gateway_channel_id": "editorial-news",
        "text": "Русский текст",
        "media": None,
    }


def test_publish_endpoint_keeps_mock_for_non_telegram():
    content = make_content()
    channel = Channel(
        id=1,
        name="Website",
        platform="web",
        language_code="en",
    )

    response = publish_route.publish(
        content_id=content.id,
        db=RouteSession([content, channel]),
    )

    assert response["platform_post_id"] == "mock_42"
