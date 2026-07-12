import pytest


@pytest.fixture(autouse=True)
def _isolate_secret_store(monkeypatch):
    """Force a fresh in-memory secret store per test so nothing ever touches the
    developer's OS keyring or writes runtime/secrets.enc into the repo (install_mcpb
    now persists user_config answers through the secret store)."""
    from ocd_core import secrets
    monkeypatch.setattr(secrets, "_store", secrets.MemoryStore())


@pytest.fixture(autouse=True)
def _isolate_cowork_store(tmp_path, monkeypatch):
    """The Cowork manager is a module singleton that persists to
    REPO_ROOT/cowork_tasks.json. Repoint BOTH the module default and the live
    singleton at a throwaway file (and clear it) so no test ever writes the repo's
    real store — the singleton captured the default path at import time."""
    from ocd_core import cowork
    store = tmp_path / "cowork_tasks.json"
    monkeypatch.setattr(cowork, "_STORE_PATH", store)
    monkeypatch.setattr(cowork.manager, "_store_path", store)
    cowork.manager.reset_for_tests()


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
