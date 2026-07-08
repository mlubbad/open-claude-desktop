"""Resilient DB: an unreachable non-SQLite DATABASE_URL falls back to local SQLite so
persistence never hard-fails (root cause of the reported history-500s)."""
import importlib


def _fresh_engine():
    from ocd_core.db import engine
    importlib.reload(engine)
    return engine


def test_unreachable_postgres_falls_back_to_sqlite(monkeypatch, tmp_path):
    # A Postgres that isn't there (bad host/port) must not leave the app dead.
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://ocd:ocd@127.0.0.1:1/ocd")
    monkeypatch.delenv("OCD_DB_FALLBACK", raising=False)
    engine = _fresh_engine()
    # Isolate the fallback target to a temp file (not the shared app ocd.db).
    monkeypatch.setattr(engine, "DEFAULT_DATABASE_URL", f"sqlite:///{tmp_path / 'fb.db'}")
    engine.reset_engine()
    fell_back = engine.ensure_reachable()
    assert fell_back is not None
    assert fell_back.startswith("sqlite:///")
    # The live engine now speaks SQLite, and a round-trip works.
    assert engine.get_engine().url.get_backend_name() == "sqlite"
    engine.init_db()
    from sqlmodel import select
    from ocd_core.db.models import Project
    with engine.session() as s:
        s.add(Project(id="fb1", name="Fallback works"))
    with engine.session() as s:
        assert "fb1" in [r.id for r in s.exec(select(Project)).all()]
    engine.reset_engine()


def test_fallback_can_be_disabled(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://ocd:ocd@127.0.0.1:1/ocd")
    monkeypatch.setenv("OCD_DB_FALLBACK", "0")
    engine = _fresh_engine()
    engine.reset_engine()
    assert engine.ensure_reachable() is None  # strict mode: no fallback
    engine.reset_engine()


def test_sqlite_default_needs_no_probe(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    engine = _fresh_engine()
    engine.reset_engine()
    assert engine.ensure_reachable() is None  # already local; nothing to fall back from
    engine.reset_engine()
