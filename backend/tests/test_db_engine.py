import importlib


def test_engine_is_lazy_and_session_roundtrips(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")  # in-memory
    from ocd_core.db import engine
    importlib.reload(engine)
    engine.reset_engine()
    engine.init_db()  # create tables
    from ocd_core.db.models import Project
    from sqlmodel import select
    with engine.session() as s:
        s.add(Project(id="p1", name="P1"))
    with engine.session() as s:
        rows = s.exec(select(Project)).all()
    assert [r.id for r in rows] == ["p1"]
    engine.reset_engine()


def test_engine_uses_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./_url_probe.db")
    from ocd_core.db import engine
    engine.reset_engine()
    assert str(engine.get_engine().url).endswith("_url_probe.db")
    engine.reset_engine()
    import os
    if os.path.exists("_url_probe.db"):
        os.remove("_url_probe.db")


def test_default_is_local_sqlite_never_postgres(monkeypatch):
    """Root-cause regression (500s on machines without a local Postgres): with no
    DATABASE_URL set, the default MUST be a SQLite file at a package-derived path —
    independent of the process cwd — never an implicit Postgres."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from ocd_core import config
    from ocd_core.db import engine
    url = engine.database_url()
    assert url.startswith("sqlite:///")
    assert "postgresql" not in url
    assert url.endswith("/ocd.db")
    assert (config.REPO_ROOT / "ocd.db").as_posix() in url


def test_file_sqlite_gets_wal_and_pragmas(monkeypatch, tmp_path):
    """Concurrency fix: a file-backed SQLite connection must come up in WAL mode
    with a busy_timeout so a second writer waits instead of erroring with
    'database is locked'. foreign_keys is enforced too."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path.as_posix()}/w.db")
    from ocd_core.db import engine
    from sqlalchemy import text
    engine.reset_engine()
    try:
        with engine.get_engine().connect() as c:
            assert c.execute(text("PRAGMA journal_mode")).scalar() == "wal"
            assert c.execute(text("PRAGMA busy_timeout")).scalar() == 5000
            assert c.execute(text("PRAGMA foreign_keys")).scalar() == 1
    finally:
        engine.reset_engine()


def test_memory_sqlite_skips_wal_but_sets_fk(monkeypatch):
    """WAL is meaningless for an in-memory DB (it needs a real file), so it must not
    be forced there — but foreign_keys still applies."""
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    from ocd_core.db import engine
    from sqlalchemy import text
    engine.reset_engine()
    try:
        with engine.get_engine().connect() as c:
            assert c.execute(text("PRAGMA journal_mode")).scalar() == "memory"
            assert c.execute(text("PRAGMA foreign_keys")).scalar() == 1
    finally:
        engine.reset_engine()
