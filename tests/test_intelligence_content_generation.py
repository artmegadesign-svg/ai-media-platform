from datetime import datetime, timezone

import pytest

from db.session import SessionLocal
from models.channel import Channel
from models.channel_content import ChannelContent
from models.content_variant import ContentVariant
from models.metric import Metric
from models.post import Post
from services.ai_engine.agents.quality_agent import QualityAgent
from services.ai_engine.services.translator_service import AITranslatorService
from services.ai_engine.services.writer_service import AIWriterService
from services.editorial.models import EditorialDecision
from services.editorial.service import EditorialService
from services.intelligence.content_generation_service import IntelligenceContentGenerationService
from services.intelligence.models import IntelligenceResult
from services.intelligence.service import IntelligenceService
from services.news.models import NewsItem
from services.news.scorer import NewsScorer
from services.news.service import NewsService
from services.trends.service import TrendService


class EditorialNewsItem(NewsItem):
    authority: float
    impact: float
    audience: float
    novelty: float


@pytest.fixture
def generation_db():
    db = SessionLocal()
    db.query(Metric).delete()
    db.query(ChannelContent).delete()
    db.query(ContentVariant).delete()
    db.query(Post).delete()
    db.query(Channel).delete()
    db.add_all([
        Channel(name="Active RU", platform="telegram", language_code="ru", is_active=True),
        Channel(name="Active EN", platform="telegram", language_code="en", is_active=True),
        Channel(name="Inactive RU", platform="telegram", language_code="ru", is_active=False),
    ])
    db.commit()
    try:
        yield db
    finally:
        db.close()


def _stub_content_engine(monkeypatch, *, approved):
    monkeypatch.setattr(AIWriterService, "generate_ru", lambda self, topic: "RU content")
    monkeypatch.setattr(AITranslatorService, "ru_to_en", lambda self, text: "EN content")
    monkeypatch.setattr(QualityAgent, "check", lambda self, content: {
        "score": 100 if approved else 20,
        "approved": approved,
        "issues": None if approved else ["Rejected in test"],
    })


def _news(now, *, title="OpenAI releases GPT-5", score=100):
    return EditorialNewsItem(
        source="OpenAI", title=title,
        url=f"https://openai.com/news/{title.replace(' ', '-').lower()}",
        published_at=now, category="model_release",
        authority=score, impact=score, audience=score, novelty=score,
    )


def _intelligence(now):
    return IntelligenceService(
        NewsService(scorer=NewsScorer(now)), TrendService(), EditorialService()
    )


def test_approved_intelligence_generates_one_complete_post(monkeypatch, generation_db):
    now = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)
    _stub_content_engine(monkeypatch, approved=True)
    approved = _intelligence(now).analyze([_news(now)])

    results = IntelligenceContentGenerationService().generate(approved)

    posts = generation_db.query(Post).all()
    variants = generation_db.query(ContentVariant).all()
    channel_contents = generation_db.query(ChannelContent).all()
    assert len(results) == 1
    assert results[0]["status"] == "published"
    assert len(posts) == 1
    assert posts[0].topic == "OpenAI releases GPT-5"
    assert sorted(item.language_code for item in variants) == ["en", "ru"]
    assert len(channel_contents) == 2
    assert len({(item.channel_id, item.post_id) for item in channel_contents}) == 2


def test_each_approved_result_is_generated_at_most_once():
    calls = []

    class RecordingGenerator:
        def generate(self, topic):
            calls.append(topic)
            return {"status": "published", "topic": topic}

    news = [
        NewsItem(source="source", title="First", url="https://example.com/first"),
        NewsItem(source="source", title="Second", url="https://example.com/second"),
    ]
    results = [IntelligenceResult(
        news=item, trend=None,
        editorial=EditorialDecision(item.id, True, "high", "news", "ok", 90),
    ) for item in news]

    generated = IntelligenceContentGenerationService(RecordingGenerator()).generate(results)

    assert calls == ["First", "Second"]
    assert len(generated) == 2


def test_rejected_intelligence_is_not_sent_to_generator():
    now = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)
    approved = _intelligence(now).analyze([_news(now, score=0)])

    class FailingGenerator:
        def generate(self, topic):
            raise AssertionError("generator must not be called")

    assert approved == []
    assert IntelligenceContentGenerationService(FailingGenerator()).generate(approved) == []


def test_quality_rejection_does_not_persist(monkeypatch, generation_db):
    now = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)
    _stub_content_engine(monkeypatch, approved=False)
    approved = _intelligence(now).analyze([_news(now)])

    results = IntelligenceContentGenerationService().generate(approved)

    assert results[0]["status"] == "rejected"
    assert generation_db.query(Post).count() == 0
    assert generation_db.query(ContentVariant).count() == 0
    assert generation_db.query(ChannelContent).count() == 0
