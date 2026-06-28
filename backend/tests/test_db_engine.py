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
