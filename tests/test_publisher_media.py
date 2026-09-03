from datetime import datetime, timedelta

import pytest

from core.settings import settings
from db.session import SessionLocal
from models.channel import Channel
from models.channel_content import ChannelContent
from models.content_variant import ContentVariant
from models.media_asset import MediaAsset
from models.post import Post
from services.publisher.factory import PublisherFactory
from services.publisher.models import PublishResult
from services.publisher.publisher_service import PublisherService


@pytest.fixture
def db():
    session = SessionLocal()
    session.query(MediaAsset).delete()
    session.query(ChannelContent).delete()
    session.query(ContentVariant).delete()
    session.query(Post).delete()
    session.query(Channel).delete()
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _publication(db, language="en"):
    channel = Channel(
        name=f"Media {language}",
        platform="telegram",
        language_code=language,
        gateway_channel_id=f"media-{language}",
    )
    post = Post(title="Media", topic="Media", ru_content="RU", en_content="EN")
    db.add_all([channel, post])
    db.flush()
    content = ChannelContent(channel_id=channel.id, post_id=post.id, status="pending")
    db.add(content)
    db.commit()
    return post, content


def _asset(
    db,
    post,
    *,
    url="https://cdn.example/image.png",
    source="generated",
    generation_status="ready",
    planning_status="complete",
    language_code=None,
    created_at=None,
):
    asset = MediaAsset(
        post_id=post.id,
        type="image",
        source=source,
        origin="test",
        license_type="generated" if source == "generated" else "official",
        url=url,
        created_at=created_at or datetime.utcnow(),
        metadata_={
            "generation_status": generation_status,
            "planning_status": planning_status,
            "language_code": language_code,
        },
    )
    db.add(asset)
    db.commit()
    return asset


def _prepared(db, content, monkeypatch):
    monkeypatch.setattr(settings, "ai_gateway_internal_token", "test-token")
    return PublisherFactory().create(db, content).media


def test_factory_keeps_text_only_publication_without_media(db, monkeypatch):
    _, content = _publication(db)

    assert _prepared(db, content, monkeypatch) is None


def test_factory_selects_ready_neutral_generated_image(db, monkeypatch):
    post, content = _publication(db)
    asset = _asset(db, post)

    assert _prepared(db, content, monkeypatch).asset_id == asset.id


@pytest.mark.parametrize(("channel_language", "asset_language"), [("en", "ru"), ("ru", "en")])
def test_factory_rejects_media_for_other_language(
    db, monkeypatch, channel_language, asset_language
):
    post, content = _publication(db, channel_language)
    _asset(db, post, language_code=asset_language)

    assert _prepared(db, content, monkeypatch) is None


@pytest.mark.parametrize("channel_language", ["ru", "en"])
def test_factory_reuses_neutral_media_for_each_language(
    db, monkeypatch, channel_language
):
    post, content = _publication(db, channel_language)
    asset = _asset(db, post)

    assert _prepared(db, content, monkeypatch).asset_id == asset.id


@pytest.mark.parametrize("generation_status", ["pending", "failed"])
def test_factory_rejects_unready_generated_media(
    db, monkeypatch, generation_status
):
    post, content = _publication(db)
    _asset(db, post, generation_status=generation_status)

    assert _prepared(db, content, monkeypatch) is None


def test_factory_never_selects_pending_placeholder(db, monkeypatch):
    post, content = _publication(db)
    _asset(db, post, url="media://pending/generate_image")

    assert _prepared(db, content, monkeypatch) is None


@pytest.mark.parametrize("url", ["", "   "])
def test_factory_rejects_empty_media_url(db, monkeypatch, url):
    post, content = _publication(db)
    _asset(db, post, url=url)

    assert _prepared(db, content, monkeypatch) is None


def test_factory_selects_deterministically_and_prefers_exact_language(db, monkeypatch):
    post, content = _publication(db, "en")
    now = datetime.utcnow()
    _asset(db, post, created_at=now - timedelta(days=2))
    expected = _asset(db, post, language_code="en", created_at=now)
    _asset(db, post, language_code="en", created_at=now + timedelta(days=1))

    assert _prepared(db, content, monkeypatch).asset_id == expected.id


def test_factory_accepts_only_reference_ready_official_image(db, monkeypatch):
    post, content = _publication(db)
    _asset(
        db,
        post,
        source="official",
        generation_status=None,
        planning_status="generation_required",
    )
    expected = _asset(
        db,
        post,
        source="official",
        generation_status=None,
        planning_status="reference_ready",
    )

    assert _prepared(db, content, monkeypatch).asset_id == expected.id


def test_publisher_failure_preserves_failed_state_and_error(db):
    _, content = _publication(db)

    class FailingPublisher:
        def publish(self, content):
            return PublishResult(success=False, error="gateway unavailable")

    result = PublisherService(db, publisher=FailingPublisher()).publish(content)

    assert result.success is False
    assert content.status == "failed"
    assert content.error_message == "gateway unavailable"
