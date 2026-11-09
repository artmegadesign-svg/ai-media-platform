import importlib
import os

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

import test_quality_issues_persistence as quality_fixtures
from db.base import Base
from repositories.base import is_unique_conflict


REVISION = "d8f3a1b6c902"
migration = importlib.import_module(f"migrations.versions.{REVISION}_add_news_source_identity")


quality_sessions = quality_fixtures.quality_sessions


def _run(engine, direction):
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            getattr(migration, direction)()


def _legacy(engine, *, duplicate=False):
    _run(engine, "downgrade")
    with engine.begin() as db:
        db.execute(text(
            "INSERT INTO posts (id, title, topic, status, ru_content, en_content, "
            "quality_approved, quality_issues, created_at) VALUES "
            "(1, 'legacy', 'same topic', 'published', 'RU', 'EN', false, 'legacy issues', CURRENT_TIMESTAMP), "
            "(2, 'manual', 'same topic', 'published', 'RU', 'EN', false, NULL, CURRENT_TIMESTAMP)"
        ))
        db.execute(text(
            "INSERT INTO channel_contents (id, post_id, channel_id, status, created_at) "
            "VALUES (1, 1, 1, 'published', CURRENT_TIMESTAMP)"
        ))
        if duplicate:
            db.execute(text(
                "INSERT INTO channel_contents (id, post_id, channel_id, status, created_at) "
                "VALUES (2, 1, 1, 'failed', CURRENT_TIMESTAMP)"
            ))


def test_upgrade_and_downgrade_preserve_legacy_data(quality_sessions):
    engine = quality_sessions.kw["bind"]
    _legacy(engine)
    _run(engine, "upgrade")
    with engine.connect() as db:
        assert list(db.execute(text("select source_key, source_url from posts order by id"))) == [(None, None)] * 2
        assert db.execute(text("select quality_issues from posts where id=1")).scalar() == "legacy issues"
    indexes = {index["name"]: index for index in inspect(engine).get_indexes("posts")}
    assert indexes["ux_posts_source_key"]["unique"]
    with pytest.raises(IntegrityError) as conflict:
        with engine.begin() as db:
            db.execute(text(
                "INSERT INTO channel_contents (id, post_id, channel_id, status, created_at) "
                "VALUES (3, 1, 1, 'pending', CURRENT_TIMESTAMP)"
            ))
    assert is_unique_conflict(
        conflict.value, "ux_channel_contents_post_channel",
        "channel_contents.post_id, channel_contents.channel_id",
    )
    with engine.begin() as db:
        db.execute(text("UPDATE posts SET source_key=:key WHERE id=1"), {"key": "a" * 64})
    with pytest.raises(IntegrityError) as conflict:
        with engine.begin() as db:
            db.execute(text("UPDATE posts SET source_key=:key WHERE id=2"), {"key": "a" * 64})
    assert is_unique_conflict(conflict.value, "ux_posts_source_key", "posts.source_key")
    _run(engine, "downgrade")
    assert "source_key" not in {c["name"] for c in inspect(engine).get_columns("posts")}
    with engine.connect() as db:
        assert db.execute(text("select count(*) from posts")).scalar() == 2
        assert db.execute(text("select status from channel_contents where id=1")).scalar() == "published"


def test_duplicate_preflight_fails_before_any_ddl(quality_sessions):
    engine = quality_sessions.kw["bind"]
    _legacy(engine, duplicate=True)
    with pytest.raises(RuntimeError, match="Duplicate ChannelContent"):
        _run(engine, "upgrade")
    assert "source_key" not in {c["name"] for c in inspect(engine).get_columns("posts")}
    assert "ux_channel_contents_post_channel" not in {
        index["name"] for index in inspect(engine).get_indexes("channel_contents")
    }
    with engine.connect() as db:
        assert list(db.execute(text("select status from channel_contents order by id"))) == [("published",), ("failed",)]


@pytest.mark.parametrize("quality_sessions", ["postgresql"], indirect=True)
def test_full_postgresql_alembic_upgrade_from_empty_database(quality_sessions, monkeypatch):
    engine = quality_sessions.kw["bind"]
    with engine.connect() as db:
        schema = db.execute(text("select current_schema()")).scalar()
    Base.metadata.drop_all(engine)
    url = engine.url.set(query={
        "host": os.environ["AMP_QUALITY_TEST_POSTGRES_SOCKET_DIR"],
        "options": f"-csearch_path={schema}",
    })
    monkeypatch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
    command.upgrade(Config("alembic.ini"), "head")
    with engine.connect() as db:
        assert db.execute(text("select version_num from alembic_version")).scalar() == REVISION
    assert {"source_key", "source_url"} <= {c["name"] for c in inspect(engine).get_columns("posts")}
    assert any(i["name"] == "ux_channel_contents_post_channel" and i["unique"]
               for i in inspect(engine).get_indexes("channel_contents"))
