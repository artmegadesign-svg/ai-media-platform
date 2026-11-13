"""Mandatory PostgreSQL smoke checks against the CI service, never the app DB."""

import os

import pytest
from sqlalchemy import create_engine, inspect, text


@pytest.fixture(scope="module")
def postgres_engine():
    url = os.environ.get("CI_POSTGRES_URL")
    required = os.environ.get("AMP_REQUIRE_POSTGRES_TESTS") == "1"
    if not url:
        if required:
            pytest.fail("CI_POSTGRES_URL is required for PostgreSQL checks")
        pytest.skip("PostgreSQL checks run in the dedicated CI job")
    engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
    if engine.url.get_backend_name() != "postgresql":
        engine.dispose()
        pytest.fail("CI_POSTGRES_URL must use PostgreSQL")
    if engine.url.host not in {"127.0.0.1", "localhost"}:
        engine.dispose()
        pytest.fail("PostgreSQL tests require a local isolated service")
    try:
        yield engine
    finally:
        engine.dispose()


def test_postgres_migrations_applied(postgres_engine):
    tables = set(inspect(postgres_engine).get_table_names())
    assert "alembic_version" in tables
    assert "posts" in tables
    with postgres_engine.connect() as connection:
        revisions = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    assert len(revisions) == 1, "Expected one applied Alembic head"


def test_postgres_connection_is_real(postgres_engine):
    with postgres_engine.connect() as connection:
        assert connection.execute(text("SELECT current_database()")).scalar_one() == "amp_ci"
