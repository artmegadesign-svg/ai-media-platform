import importlib
import os

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text

import test_quality_issues_persistence as quality_fixtures
from db.base import Base
from models.channel_content import ChannelContent
from models.post import Post

quality_sessions = quality_fixtures.quality_sessions
migration = importlib.import_module('migrations.versions.f2b7d9a4c601_add_publication_claim_diagnostics')
FIELDS = {'claim_token', 'claimed_at', 'error_code', 'gateway_http_status', 'retry_after_at'}


def run(engine, direction):
    with engine.begin() as db:
        with Operations.context(MigrationContext.configure(db)):
            getattr(migration, direction)()


def test_upgrade_downgrade_preserve_legacy_and_constraints(quality_sessions):
    engine = quality_sessions.kw['bind']
    with quality_sessions() as db:
        post = Post(title='Legacy', topic='Legacy', ru_content='RU', en_content='EN',
                    quality_issues='legacy issues', source_key='a' * 64, source_url='https://example.com/a')
        db.add(post)
        db.flush()
        db.add(ChannelContent(post_id=post.id, channel_id=1, status='published', platform_post_id='123'))
        db.commit()
    run(engine, 'downgrade')
    assert not FIELDS & {c['name'] for c in inspect(engine).get_columns('channel_contents')}
    run(engine, 'upgrade')
    assert FIELDS <= {c['name'] for c in inspect(engine).get_columns('channel_contents')}
    with engine.connect() as db:
        assert db.execute(text('select status, platform_post_id, claim_token from channel_contents')).one() == ('published', '123', None)
        assert db.execute(text('select quality_issues, source_key from posts')).one() == ('legacy issues', 'a' * 64)
    assert any(i['name'] == 'ux_channel_contents_post_channel' and i['unique']
               for i in inspect(engine).get_indexes('channel_contents'))
    assert any(i['name'] == 'ux_posts_source_key' and i['unique']
               for i in inspect(engine).get_indexes('posts'))


@pytest.mark.parametrize('status', ['publishing', 'unknown'])
def test_downgrade_refuses_unresolved_before_any_ddl(quality_sessions, status):
    engine = quality_sessions.kw['bind']
    with quality_sessions() as db:
        post = Post(title='Unresolved', topic='Unresolved', ru_content='RU', en_content='EN')
        db.add(post)
        db.flush()
        db.add(ChannelContent(post_id=post.id, channel_id=1, status=status, claim_token='claim'))
        db.commit()
    with pytest.raises(RuntimeError, match='Reconcile unresolved'):
        run(engine, 'downgrade')
    assert FIELDS <= {c['name'] for c in inspect(engine).get_columns('channel_contents')}
    with engine.connect() as db:
        assert db.execute(text('select status, claim_token from channel_contents')).one() == (status, 'claim')


@pytest.mark.parametrize('quality_sessions', ['postgresql'], indirect=True)
def test_full_postgresql_alembic_chain_and_new_revision_roundtrip(quality_sessions, monkeypatch):
    engine = quality_sessions.kw['bind']
    with engine.connect() as db:
        schema = db.execute(text('select current_schema()')).scalar()
    Base.metadata.drop_all(engine)
    url = engine.url.set(query={'host': os.environ['AMP_QUALITY_TEST_POSTGRES_SOCKET_DIR'],
                                'options': f'-csearch_path={schema}'})
    monkeypatch.setenv('DATABASE_URL', url.render_as_string(hide_password=False))
    config = Config('alembic.ini')
    command.upgrade(config, 'head')
    with engine.connect() as db:
        assert db.execute(text('select version_num from alembic_version')).scalar() == migration.revision
    command.downgrade(config, migration.down_revision)
    assert not FIELDS & {c['name'] for c in inspect(engine).get_columns('channel_contents')}
    command.upgrade(config, 'head')
    assert FIELDS <= {c['name'] for c in inspect(engine).get_columns('channel_contents')}
