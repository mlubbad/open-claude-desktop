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
