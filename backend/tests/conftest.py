import pytest


@pytest.fixture
def db(monkeypatch):
    """Fresh in-memory SQLite DB per test, with tables created."""
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    from ocd_core.db import engine
    engine.reset_engine()
    engine.init_db()
    yield
    engine.reset_engine()
