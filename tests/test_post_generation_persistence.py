import asyncio

import pytest
from fastapi import HTTPException

from app.routes.posts import create_post
from app.schemas.post import PostCreate
from db.session import SessionLocal
from models.channel import Channel
from models.channel_content import ChannelContent
from models.content_variant import ContentVariant
from models.metric import Metric
from models.post import Post
from services.ai_engine.agents.quality_agent import QualityAgent
from services.ai_engine.services.translator_service import AITranslatorService
from services.ai_engine.services.writer_service import AIWriterService


@pytest.fixture
def generation_db():
    db = SessionLocal()
    db.query(Metric).delete()
    db.query(ChannelContent).delete()
    db.query(ContentVariant).delete()
    db.query(Post).delete()
    db.query(Channel).delete()
    db.add_all(
        [
            Channel(name="Active RU", platform="telegram", language_code="ru", is_active=True),
            Channel(name="Active EN", platform="telegram", language_code="en", is_active=True),
            Channel(name="Inactive RU", platform="telegram", language_code="ru", is_active=False),
            Channel(name="Active DE", platform="telegram", language_code="de", is_active=True),
        ]
    )
    db.commit()
    try:
        yield db
    finally:
        db.close()


def _stub_generation(monkeypatch, *, approved):
    monkeypatch.setattr(AIWriterService, "generate_ru", lambda self, topic: "RU content")
    monkeypatch.setattr(AITranslatorService, "ru_to_en", lambda self, text: "EN content")
    monkeypatch.setattr(
        QualityAgent,
        "check",
        lambda self, content: {
            "score": 100 if approved else 20,
            "approved": approved,
            "issues": None if approved else ["Rejected in test"],
        },
    )


def test_approved_post_request_persists_each_record_once(monkeypatch, generation_db):
    _stub_generation(monkeypatch, approved=True)

    result = asyncio.run(create_post(PostCreate(topic="Persistence test")))

    posts = generation_db.query(Post).all()
    variants = generation_db.query(ContentVariant).all()
    channel_contents = generation_db.query(ChannelContent).all()

    assert result["id"] == posts[0].id
    assert result["topic"] == "Persistence test"
    assert result["ru_content"] == "RU content"
    assert result["en_content"] == "EN content"
    assert result["status"] == "published"
    assert result["quality_score"] == 100
    assert result["quality_approved"] is True
    assert result["quality_issues"] is None
    assert len(posts) == 1
    assert sorted(variant.language_code for variant in variants) == ["en", "ru"]
    assert len(channel_contents) == 2
    assert len({(item.channel_id, item.post_id) for item in channel_contents}) == 2


def test_rejected_post_request_does_not_persist(monkeypatch, generation_db):
    _stub_generation(monkeypatch, approved=False)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(create_post(PostCreate(topic="Rejected test")))

    assert exc_info.value.status_code == 422
    assert generation_db.query(Post).count() == 0
    assert generation_db.query(ContentVariant).count() == 0
    assert generation_db.query(ChannelContent).count() == 0
