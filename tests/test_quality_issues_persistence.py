import asyncio
import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from app.routes.posts import create_post
from app.schemas.post import PostCreate, PostResponse
from db.base import Base
from models.channel import Channel
from models.channel_content import ChannelContent
from models.content_variant import ContentVariant
from models.metric import Metric
from models.post import Post
from services import analytics_service
from services.ai_engine.agents.quality_agent import QualityAgent
from services.ai_engine.pipeline.content_pipeline import ContentPipeline
from services.ai_engine.services import post_service
from services.ai_engine.services.translator_service import AITranslatorService
from services.ai_engine.services.writer_service import AIWriterService


@pytest.fixture(params=["sqlite", "postgresql"])
def quality_sessions(request, tmp_path, monkeypatch):
    """Use SQLite or an explicitly supplied disposable local PostgreSQL socket.

    Never use DATABASE_URL or production credentials. PostgreSQL tests own only
    a unique schema in the dedicated amp_quality_test database.
    Set AMP_QUALITY_REQUIRE_POSTGRES=1 to make a missing test socket an error.
    """
    schema = None
    if request.param == "sqlite":
        engine = create_engine(f"sqlite:///{tmp_path / 'quality.db'}")
    else:
        socket_dir = os.getenv("AMP_QUALITY_TEST_POSTGRES_SOCKET_DIR")
        if not socket_dir:
            if os.getenv("AMP_QUALITY_REQUIRE_POSTGRES") == "1":
                pytest.fail(
                    "Strict PostgreSQL mode requires AMP_QUALITY_TEST_POSTGRES_SOCKET_DIR"
                )
            pytest.skip("Disposable PostgreSQL socket was not supplied")
        socket_path = Path(socket_dir).resolve()
        if (
            socket_path.parent != Path(tempfile.gettempdir()).resolve()
            or not socket_path.name.startswith("amp_quality_test_")
        ):
            pytest.fail("Refusing a non-test PostgreSQL socket directory")
        schema = f"quality_issues_{uuid4().hex}"
        engine = create_engine(
            "postgresql+psycopg2://amp_quality_test@/amp_quality_test",
            connect_args={"host": str(socket_path), "options": f"-csearch_path={schema}"},
        )
        with engine.begin() as db:
            identity = db.execute(text("select current_database(), current_user")).one()
            assert tuple(identity) == ("amp_quality_test", "amp_quality_test")
            assert db.execute(text("show listen_addresses")).scalar() == ""
            db.execute(CreateSchema(schema))

    try:
        Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine, autoflush=False)
        monkeypatch.setattr(post_service, "SessionLocal", sessions)
        monkeypatch.setattr(analytics_service, "SessionLocal", sessions)
        with sessions() as db:
            db.add_all([
                Channel(name="Quality RU", platform="telegram", language_code="ru"),
                Channel(name="Quality EN", platform="telegram", language_code="en"),
            ])
            db.commit()
        yield sessions
    finally:
        try:
            if schema is not None:
                with engine.begin() as db:
                    db.execute(DropSchema(schema, cascade=True))
        finally:
            engine.dispose()


def _counts(sessions):
    with sessions() as db:
        return tuple(db.query(model).count() for model in (
            Post, ContentVariant, ChannelContent, Metric,
        ))


def _assert_round_trip(sessions, saved, expected):
    assert saved["quality_issues"] == expected
    with sessions() as db:
        post = db.get(Post, saved["id"])
        assert post.quality_issues == expected
        raw = db.execute(
            text("select quality_issues from posts where id=:id"), {"id": post.id},
        ).scalar()
        assert raw == expected
        assert PostResponse.model_validate(post).quality_issues == expected
    latest = post_service.PostService().get_latest()
    assert latest[0].id == saved["id"]
    assert latest[0].quality_issues == expected
    assert PostResponse.model_validate(latest[0]).quality_issues == expected


@pytest.mark.parametrize("quality", [None, {}, {"score": 100, "approved": True},
    {"issues": None}, {"issues": []},
])
def test_empty_or_absent_issues_are_null(quality_sessions, quality):
    saved = post_service.PostService().save("Empty issues", "RU", "EN", quality)

    _assert_round_trip(quality_sessions, saved, None)
    assert _counts(quality_sessions) == (1, 2, 2, 1)


def test_nonempty_issues_are_unicode_json_with_lossless_round_trip(quality_sessions):
    issues = ['Ошибка: "пример"', "строка\nтабуляция\tпуть\\файл", "эмодзи 🌍"]
    quality = {"score": 50, "approved": False, "issues": issues}

    saved = post_service.PostService().save("JSON issues", "RU", "EN", quality)

    encoded = saved["quality_issues"]
    assert isinstance(encoded, str)
    assert encoded == json.dumps(issues, ensure_ascii=False)
    assert "Ошибка" in encoded
    assert json.loads(encoded) == issues
    assert quality["issues"] is issues  # The agent's list must remain unchanged.
    _assert_round_trip(quality_sessions, saved, encoded)
    assert _counts(quality_sessions) == (1, 2, 2, 1)


@pytest.mark.parametrize("issues", ["", "legacy issue", "{}", "[]", '["Ошибка"]'])
def test_existing_strings_are_not_reencoded(quality_sessions, issues):
    saved = post_service.PostService().save("Legacy issues", "RU", "EN", {"issues": issues})

    _assert_round_trip(quality_sessions, saved, issues)


@pytest.mark.parametrize("issues", [
    0, False, 1.5, {}, (), b"text", ["valid", 1], [None], [{}], [[]],
])
def test_invalid_issues_fail_before_database_access_without_partial_records(
    quality_sessions, monkeypatch, issues,
):
    before = _counts(quality_sessions)

    def unexpected_session():
        pytest.fail("Invalid issues must be rejected before opening a DB session")

    with monkeypatch.context() as guard:
        guard.setattr(post_service, "SessionLocal", unexpected_session)
        with pytest.raises(TypeError, match="issues"):
            post_service.PostService().save("Invalid issues", "RU", "EN", {"issues": issues})

    assert _counts(quality_sessions) == before == (0, 0, 0, 0)
    saved = post_service.PostService().save("Next valid save", "RU", "EN", {"issues": []})
    _assert_round_trip(quality_sessions, saved, None)


def test_real_approved_quality_agent_persists_complete_post(quality_sessions, monkeypatch):
    ru = "HOOK\n" + "Проверенный текст " * 20 + "\nINSIGHT\nVALUE\nCONCLUSION"
    quality = QualityAgent().check(ru)
    assert quality == {"score": 100, "approved": True, "issues": []}
    monkeypatch.setattr(AIWriterService, "generate_ru", lambda *_: ru)
    monkeypatch.setattr(AITranslatorService, "ru_to_en", lambda *_: "EN content")

    saved = asyncio.run(create_post(PostCreate(topic="Real QualityAgent")))

    assert saved["quality_approved"] is True
    assert saved["quality_score"] == 100
    _assert_round_trip(quality_sessions, saved, None)
    assert _counts(quality_sessions) == (1, 2, 2, 1)


def test_real_rejected_quality_agent_keeps_list_and_creates_no_records(
    quality_sessions, monkeypatch,
):
    monkeypatch.setattr(AIWriterService, "generate_ru", lambda *_: "bad")
    monkeypatch.setattr(AITranslatorService, "ru_to_en", lambda *_: "EN")
    expected = QualityAgent().check("bad")["issues"]

    result = ContentPipeline().generate_full_content("Rejected quality")

    assert result["status"] == "rejected"
    assert result["issues"] == result["quality_issues"] == expected
    assert isinstance(result["quality_issues"], list)
    with pytest.raises(HTTPException) as error:
        asyncio.run(create_post(PostCreate(topic="Rejected quality")))
    assert error.value.status_code == 422
    assert error.value.detail["quality_issues"] == expected
    assert _counts(quality_sessions) == (0, 0, 0, 0)
