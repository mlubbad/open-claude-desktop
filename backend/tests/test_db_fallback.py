"""Containment DB posture: strict by default; local fallback is an explicit opt-in."""
import importlib

import pytest


def _fresh_engine():
    from ocd_core.db import engine
    importlib.reload(engine)
    return engine


def _make_postgres_unreachable(monkeypatch, engine):
    """Avoid relying on host firewall timeout behavior for the failure path."""
    real_build = engine._build_engine

    def build(url):
        if not url.startswith("sqlite"):
            raise ConnectionError("database unreachable")
        return real_build(url)

    monkeypatch.setattr(engine, "_build_engine", build)


def test_unreachable_postgres_falls_back_to_sqlite(monkeypatch, tmp_path):
    # Local-only operators may explicitly accept degraded SQLite persistence.
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://ocd:ocd@127.0.0.1:1/ocd")
    monkeypatch.setenv("OCD_DB_FALLBACK", "1")
    engine = _fresh_engine()
    _make_postgres_unreachable(monkeypatch, engine)
    # Isolate the fallback target to a temp file (not the shared app ocd.db).
    monkeypatch.setattr(engine, "DEFAULT_DATABASE_URL", f"sqlite:///{tmp_path / 'fb.db'}")
    engine.reset_engine()
    fell_back = engine.ensure_reachable()
    assert fell_back is not None
    assert fell_back.startswith("sqlite:///")
    # The live engine now speaks SQLite, and a round-trip works.
    assert engine.get_engine().url.get_backend_name() == "sqlite"
    engine.init_db()
    from ocd_core.db.models import Project
    from sqlmodel import select
    with engine.session() as s:
        s.add(Project(id="fb1", name="Fallback works"))
    with engine.session() as s:
        assert "fb1" in [r.id for r in s.exec(select(Project)).all()]
    engine.reset_engine()


def test_fallback_is_disabled_by_default(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://ocd:ocd@127.0.0.1:1/ocd")
    monkeypatch.delenv("OCD_DB_FALLBACK", raising=False)
    engine = _fresh_engine()
    _make_postgres_unreachable(monkeypatch, engine)
    engine.reset_engine()
    with pytest.raises(RuntimeError, match="unreachable"):
        engine.ensure_reachable()
    assert engine.fell_back() is False
    engine.reset_engine()


def test_fallback_zero_fails_startup(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://ocd:ocd@127.0.0.1:1/ocd")
    monkeypatch.setenv("OCD_DB_FALLBACK", "0")
    engine = _fresh_engine()
    _make_postgres_unreachable(monkeypatch, engine)
    engine.reset_engine()
    with pytest.raises(RuntimeError, match="unreachable"):
        engine.ensure_reachable()
    assert engine.fell_back() is False
    engine.reset_engine()


def test_sqlite_default_needs_no_probe(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    engine = _fresh_engine()
    _make_postgres_unreachable(monkeypatch, engine)
    engine.reset_engine()
    assert engine.ensure_reachable() is None  # already local; nothing to fall back from
    engine.reset_engine()
