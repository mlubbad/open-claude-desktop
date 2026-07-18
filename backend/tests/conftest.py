import os

import pytest

_AUTH_ENV_VARS = ("APP_USERNAME", "APP_PASSWORD", "CHAINLIT_AUTH_SECRET",
                  "OCD_AUTH_SECRET", "AJ360_AUTH_SECRET", "APP_AUTH_SECRET")


@pytest.fixture(autouse=True, scope="session")
def _no_ambient_auth_env():
    """Isolate tests from the developer's real .env auth config.

    app.main calls load_dotenv() at import time (so a bare local `uvicorn` run
    picks up ZHIPU_API_KEY without a wrapper). If the developer's .env also sets
    APP_USERNAME/APP_PASSWORD/*_AUTH_SECRET, that import silently flips auth on
    for the rest of the process -- most REST tests assume auth-disabled-by-default
    and send no Bearer token, so whichever test happens to import app.main first
    would 401 mid-test (load_dotenv() fires inside that test's own `client`
    fixture, after any pre-clear already ran -- a plain "clear before" can't
    beat that race). Force the one-time import (and its load_dotenv() side
    effect) here instead, under our control, before any test/fixture runs --
    every later `from backend.app.main import app` is then a cached no-op --
    and scrub the auth vars right after. Per-test monkeypatch.setenv still
    overrides freely for the tests that exercise auth.
    """
    import backend.app.main  # noqa: F401  import side effect: load_dotenv()
    for v in _AUTH_ENV_VARS:
        os.environ.pop(v, None)


@pytest.fixture
def db(monkeypatch, tmp_path):
    """Fresh in-memory SQLite DB + isolated filesystem per test."""
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    from ocd_core import config
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(config, "KNOWLEDGE_DIR", tmp_path / "knowledge")
    monkeypatch.setattr(config, "CHROMA_PATH", str(tmp_path / "chroma_db"))
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    from ocd_core.db import engine
    engine.reset_engine()
    engine.init_db()
    yield
    engine.reset_engine()
