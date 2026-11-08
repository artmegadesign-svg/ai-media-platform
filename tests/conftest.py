import importlib.util
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path

import pytest


_TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="ai_media_pytest_"))
_TEST_DB_PATH = _TEST_DB_DIR / "test.db"
_TEST_DATABASE_URL = f"sqlite:///{_TEST_DB_PATH}"
_engine = None

# Configure an isolated SQLite database before application modules import db.session.
os.environ["DATABASE_URL"] = _TEST_DATABASE_URL

os.environ.setdefault("AI_GATEWAY_URL", "http://gateway.example:9000")
os.environ.setdefault("POSTGRES_DB", "ai_media_test")
os.environ.setdefault("POSTGRES_USER", "ai_media_test")
os.environ.setdefault("POSTGRES_PASSWORD", "ai_media_test")

# Some minimal test environments omit optional dotenv loading support. Production
# installs python-dotenv through pydantic-settings; the shim is only for tests.
if importlib.util.find_spec("dotenv") is None:
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *args, **kwargs: False
    sys.modules["dotenv"] = dotenv

# Keep tests runnable in stripped-down environments while preserving production's
# pydantic-settings dependency when it is installed.
if importlib.util.find_spec("pydantic_settings") is None:
    from pydantic import BaseModel

    pydantic_settings = types.ModuleType("pydantic_settings")

    class BaseSettings(BaseModel):
        def __init__(self, **data):
            env_values = {
                name: os.environ[name.upper()]
                for name in type(self).model_fields
                if name.upper() in os.environ and name not in data
            }
            env_values.update(data)
            super().__init__(**env_values)

    pydantic_settings.BaseSettings = BaseSettings
    pydantic_settings.SettingsConfigDict = lambda **kwargs: kwargs
    sys.modules["pydantic_settings"] = pydantic_settings


def pytest_configure(config):
    global _engine

    from db.base import Base
    from db.session import engine
    import models  # noqa: F401 - register all SQLAlchemy models on Base.metadata

    _engine = engine
    _assert_test_database()
    Base.metadata.create_all(bind=_engine)


def _assert_test_database():
    from db.session import SessionLocal, engine

    if (
        engine.url.get_backend_name() != "sqlite"
        or not engine.url.database
        or Path(engine.url.database).resolve() != _TEST_DB_PATH.resolve()
        or SessionLocal.kw.get("bind") is not engine
    ):
        raise RuntimeError("Refusing to run pytest against a non-isolated database")


@pytest.fixture(autouse=True)
def isolated_test_database():
    """Reset the existing temporary SQLite schema before each test.

    Tests and services commit their own sessions; rollback alone cannot isolate them.
    """
    from db.base import Base

    _assert_test_database()
    Base.metadata.drop_all(bind=_engine)
    Base.metadata.create_all(bind=_engine)
    yield


@pytest.fixture
def isolated_db(isolated_test_database):
    from db.session import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


def pytest_unconfigure(config):
    try:
        if _engine is not None:
            _engine.dispose()
    finally:
        shutil.rmtree(_TEST_DB_DIR, ignore_errors=True)
