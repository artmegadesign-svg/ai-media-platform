"""Caption fallbacks preserve content/credit and never trigger additional AI work."""

import json

import httpx
import pytest

from models.channel import Channel
from models.channel_content import ChannelContent
from models.content_variant import ContentVariant
from models.media_asset import MediaAsset
from models.post import Post
from services.publisher import factory as factory_module
from services.publisher.adapters.telegram import TelegramPublisher
from services.publisher.media import PublicationMedia
from services.publisher.models import PublicationReference


def media(credit="Source: Google."):
    return PublicationMedia(1, "image", "https://cdn.example/image.jpg", credit)


def send(text, image):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "status": "published",
                "provider": "telegram",
                "channel_id": "test-channel",
                "external_message_id": 123,
            },
        )

    publisher = TelegramPublisher(
        "https://gateway.example",
        "test-only",
        "test-channel",
        text,
        media=image,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = publisher.publish(PublicationReference(1, 1, 1))
    assert publisher.text == text and publisher.media == image
    return result, requests


def test_fitting_html_is_exactly_the_existing_rendering():
    text = "Новость < 5 & > 2\n\nФакт. 🙂"
    image = media("Source: Owner & <Artist>.")
    rendered, mode = TelegramPublisher.prepare_publication(text, image)
    assert mode == "HTML"
    assert rendered == TelegramPublisher.render_html(text, 1024, credit=image.credit)
    assert "&lt;Artist&gt;" in rendered


@pytest.mark.parametrize(
    "text,credit",
    [
        ("N" * 900, "&" * 30),
        ("< & > " * 140, "Source: <Artist> & Owner."),
        ("Ж" * 1001, "Source: Google."),
    ],
)
def test_html_overflow_uses_complete_plain_text_without_interpreting_markup(
    text, credit
):
    image = media(credit)
    expected = text.strip() + "\n\n" + credit
    assert TelegramPublisher.prepare_publication(text, image) == (expected, None)
    result, requests = send(text, image)
    assert result.success
    assert requests[0]["text"] == expected
    assert requests[0]["parse_mode"] is None
    assert requests[0]["media"] == {"type": "image", "url": image.url}


def test_only_redundant_spacing_is_normalized_and_credit_is_verbatim():
    headline = "Headline " + " " * 700
    paragraph = "Fact:  1 000 units.\t\tDate: 2026-11-11. " + " " * 700
    last = "Not available yet. https://example.com/a?x=1&y=2"
    text = headline + "\n\n\n\n" + paragraph + "\n\n\n" + last
    credit = "Source:  Owner.\nLicense: CC BY 4.0.  "
    expected = (
        "Headline\n\nFact: 1 000 units. Date: 2026-11-11.\n\n" + last + "\n\n" + credit
    )
    assert TelegramPublisher.prepare_publication(text, media(credit)) == (
        expected,
        None,
    )
    assert text.startswith(headline)  # Preparation has not rewritten the input.


@pytest.mark.parametrize(
    "text,credit",
    [
        ("x" * 1024, "c"),
        ("x" * 900, "🙂" * 70),
        ("Short news", "c" * 1024),
        ("🙂" * 513, "credit"),
    ],
)
def test_no_external_call_when_full_news_and_credit_cannot_fit(
    text, credit, monkeypatch
):
    def forbidden(*args, **kwargs):
        raise AssertionError("AI must not be invoked to fit a caption")

    monkeypatch.setattr(
        "services.ai_engine.services.writer_service.AIWriterService.generate_ru",
        forbidden,
    )
    monkeypatch.setattr(
        "services.ai_engine.services.translator_service.AITranslatorService.ru_to_en",
        forbidden,
    )
    monkeypatch.setattr(
        "services.media.adapters.ai_gateway.AIGatewayImageGenerationProvider.generate",
        forbidden,
    )
    image = media(credit)
    with pytest.raises(ValueError, match="1024"):
        TelegramPublisher.prepare_publication(text, image)
    result, requests = send(text, image)
    assert result.error_code == "publication_not_ready"
    assert requests == []


def test_plain_boundary_includes_utf16_and_full_credit():
    credit = "Source: Google."
    text = "🙂" * 200 + "&" * (1024 - 400 - 2 - len(credit))
    prepared, mode = TelegramPublisher.prepare_publication(text, media(credit))
    assert mode is None
    assert len(prepared.encode("utf-16-le")) // 2 == 1024
    with pytest.raises(ValueError):
        TelegramPublisher.prepare_publication(text + "x", media(credit))


@pytest.mark.parametrize("bad", ["<b>News</b>" + "x" * 1100, "**News**" + "x" * 1100])
def test_fallback_does_not_bypass_existing_content_validation(bad):
    result, requests = send(bad, media())
    assert result.error_code == "publication_not_ready"
    assert requests == []


def test_text_only_publications_keep_existing_html_behavior():
    text = "News\n\nFacts & details."
    assert TelegramPublisher.prepare_publication(text) == (
        TelegramPublisher.render_html(text),
        "HTML",
    )
    with pytest.raises(ValueError):
        TelegramPublisher.prepare_publication("x" * 4096)


@pytest.mark.parametrize("language", ["ru", "en"])
@pytest.mark.parametrize("padded", [False, True])
def test_factory_and_adapter_agree_without_changing_post_or_variants(
    isolated_db, monkeypatch, language, padded
):
    db = isolated_db
    canonical = "N" * 450 + "\n\n" + "F" * 450
    text = (
        ("N" * 450 + " " * 800 + "\n\n\n\n" + "F" * 450 + " " * 800)
        if padded
        else canonical
    )
    credit = "&" * 30
    post = Post(title="News", topic="News", ru_content=text, en_content=text)
    channel = Channel(
        name="Caption",
        platform="telegram",
        language_code=language,
        gateway_channel_id="test-channel",
    )
    db.add_all([post, channel])
    db.flush()
    variant = ContentVariant(post_id=post.id, language_code=language, content=text)
    content = ChannelContent(post_id=post.id, channel_id=channel.id, status="pending")
    asset = MediaAsset(
        post_id=post.id,
        type="image",
        source="official",
        origin="test",
        license_type="reviewed_permission",
        url="https://cdn.example/image.jpg",
        metadata_={
            "planning_status": "reference_ready",
            "usage": {
                "usage_allowed": True,
                "attribution_required": True,
                "attribution": credit,
                "license_type": "reviewed_permission",
                "terms_url": "https://example.com/terms",
                "evidence": "Reviewed exact-image fixture permission",
            },
        },
    )
    db.add_all([variant, content, asset])
    db.commit()
    monkeypatch.setattr(
        factory_module.settings, "ai_gateway_internal_token", "test-only"
    )
    publisher = factory_module.PublisherFactory().create(db, content)
    expected = TelegramPublisher.prepare_publication(text, publisher.media)
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "status": "published",
                "provider": "telegram",
                "channel_id": "test-channel",
                "external_message_id": 123,
            },
        )

    publisher.client = httpx.Client(transport=httpx.MockTransport(handler))
    assert publisher.publish(
        PublicationReference(content.id, post.id, channel.id)
    ).success
    assert (requests[0]["text"], requests[0]["parse_mode"]) == expected
    assert expected == (canonical + "\n\n" + credit, None)
    assert not db.dirty
    db.expire_all()
    assert db.get(Post, post.id).ru_content == text
    assert db.get(Post, post.id).en_content == text
    assert db.get(ContentVariant, variant.id).content == text
