import pytest


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
