from datetime import datetime, timezone

import pytest

from db.session import SessionLocal
from models.channel_content import ChannelContent
from models.content_variant import ContentVariant
from models.media_asset import MediaAsset
from models.post import Post
from services.ai_engine.agents.quality_agent import QualityAgent
from services.ai_engine.services.translator_service import AITranslatorService
from services.ai_engine.services.writer_service import AIWriterService
from services.editorial.models import EditorialDecision
from services.intelligence.content_generation_service import (
    IntelligenceContentGenerationService,
)
from services.intelligence.models import IntelligenceResult
from services.media.generation_service import GeneratedMedia
from services.media.planning_service import MediaPlanningService
from services.media.resolver import MediaDecision, MediaStrategy, MediaType
from services.news.models import NewsItem


@pytest.fixture
def db():
    session = SessionLocal()
    session.query(MediaAsset).delete()
    session.query(ChannelContent).delete()
    session.query(ContentVariant).delete()
    session.query(Post).delete()
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _result(title="Media bridge"):
    news = NewsItem(
        source="Example News",
        title=title,
        url="https://example.com/story",
        image_url="https://example.com/article-image.jpg",
        content="Story body",
        category="technology",
        published_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )
    return IntelligenceResult(
        news=news,
        trend=None,
        editorial=EditorialDecision(news.id, True, "high", "news", "ok", 90),
    )


def _content(monkeypatch, approved=True):
    monkeypatch.setattr(AIWriterService, "generate_ru", lambda *_: "RU")
    monkeypatch.setattr(AITranslatorService, "ru_to_en", lambda *_: "EN")
    monkeypatch.setattr(
        QualityAgent,
        "check",
        lambda *_: {"score": 90, "approved": approved, "issues": []},
    )


class RecordingProvider:
    def __init__(self, *, fail=False):
        self.calls = []
        self.fail = fail

    def generate(self, *, prompt, language_code):
        self.calls.append((prompt, language_code))
        if self.fail:
            raise RuntimeError("provider unavailable")
        return GeneratedMedia(url="https://cdn.example/generated.png", provider="fake")


def test_generated_fallback_runs_after_post_persistence(monkeypatch, db):
    _content(monkeypatch)
    provider = RecordingProvider()

    result = IntelligenceContentGenerationService(image_provider=provider).generate(
        [_result()]
    )[0]

    assert db.query(Post).count() == 1
    assert db.query(MediaAsset).count() == 1
    asset = db.query(MediaAsset).one()
    assert asset.post_id == result["post_id"]
    assert result["media_strategy"] == "generate_image"
    assert result["media_generation_status"] == "ready"
    assert result["media_url"] == "https://cdn.example/generated.png"
    assert asset.metadata_["generation_status"] == "ready"
    assert provider.calls == [("Media bridge", None)]


def test_reference_ready_plan_does_not_execute_generation(monkeypatch, db):
    _content(monkeypatch)
    provider = RecordingProvider()

    class OfficialResolver:
        def resolve(self, metadata):
            return MediaDecision(
                strategy=MediaStrategy.USE_OFFICIAL_IMAGE,
                media_type=MediaType.IMAGE,
                source="official",
                origin="Example",
                source_url="https://official.example/image.png",
                license_type="press",
                reason="verified fixture",
            )

    service = IntelligenceContentGenerationService(
        image_provider=provider,
        planning_service_factory=lambda session: MediaPlanningService(
            session, OfficialResolver()
        ),
    )
    result = service.generate([_result()])[0]

    assert db.query(MediaAsset).count() == 1
    assert result["media_strategy"] == "use_official_image"
    assert result["media_generation_status"] == "not_required"
    assert provider.calls == []


def test_quality_rejection_skips_all_media(monkeypatch, db):
    _content(monkeypatch, approved=False)
    provider = RecordingProvider()

    result = IntelligenceContentGenerationService(image_provider=provider).generate(
        [_result()]
    )[0]

    assert result["content_generation_status"] == "rejected"
    assert db.query(Post).count() == 0
    assert db.query(MediaAsset).count() == 0
    assert provider.calls == []


def test_each_result_gets_at_most_one_post_and_plan(monkeypatch, db):
    _content(monkeypatch)
    results = IntelligenceContentGenerationService().generate(
        [_result("First"), _result("Second")]
    )

    assert len(results) == 2
    assert db.query(Post).count() == 2
    assert db.query(MediaAsset).count() == 2
    assert len({item["post_id"] for item in results}) == 2


def test_media_failure_does_not_duplicate_content(monkeypatch, db):
    _content(monkeypatch)
    provider = RecordingProvider(fail=True)

    result = IntelligenceContentGenerationService(image_provider=provider).generate(
        [_result()]
    )[0]

    assert result["media_generation_status"] == "failed"
    assert db.query(Post).count() == 1
    assert db.query(MediaAsset).count() == 1
    assert db.query(ContentVariant).count() == 2
    asset = db.query(MediaAsset).one()
    assert asset.metadata_["generation_status"] == "failed"
    channel_content = db.query(ChannelContent).all()
    assert len(channel_content) == len(
        {(item.channel_id, item.post_id) for item in channel_content}
    )
