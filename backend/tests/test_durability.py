"""Crash / migration durability (audit Week-3).

* Cowork tasks flush their transcript INCREMENTALLY, not only at the end, so a crash
  mid-run keeps the work so far instead of just the empty shell saved at start.
* A SQLite schema migration snapshots the DB first (VACUUM INTO), so a botched ALTER
  is recoverable — and only when a migration actually runs.
"""
import asyncio
import json

from sqlalchemy import inspect, text

# --- Cowork incremental flush ---------------------------------------------------

def test_cowork_flushes_transcript_incrementally(monkeypatch, tmp_path):
    from ocd_core import cowork
    monkeypatch.setattr(cowork, "_FLUSH_INTERVAL_SEC", 0.0)  # flush on every event
    mgr = cowork.CoworkManager(store_path=tmp_path / "tasks.json")

    saves = {"n": 0}
    real_save = mgr._save

    def counting_save():
        saves["n"] += 1
        real_save()
    monkeypatch.setattr(mgr, "_save", counting_save)

    async def gen():
        for i in range(5):
            yield {"type": "delta", "scope": "answer", "text": f"e{i}"}

    async def go():
        t = mgr.start("goal", gen)
        await t.handle

    asyncio.run(go())

    # Old code saved twice total (start + finally). Incremental flushing adds one per
    # event, so well above 2.
    assert saves["n"] >= 5
    # The persisted store carries the full transcript.
    data = json.loads((tmp_path / "tasks.json").read_text())
    assert data and len(data[0]["events"]) == 5


# --- Pre-migration SQLite backup ------------------------------------------------

def _use_file_db(monkeypatch, tmp_path):
    db = tmp_path / "ocd.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db.as_posix()}")
    from ocd_core.db import engine
    engine.reset_engine()
    return engine, db


def test_backup_written_before_a_real_migration(monkeypatch, tmp_path):
    engine, db = _use_file_db(monkeypatch, tmp_path)
    try:
        # Seed an OLD-schema conversation table missing the added columns.
        with engine.get_engine().begin() as c:
            c.execute(text("CREATE TABLE conversation (id VARCHAR PRIMARY KEY, "
                           "project_id VARCHAR, title VARCHAR, transcript JSON, "
                           "created_at DATETIME, updated_at DATETIME)"))
            c.execute(text("INSERT INTO conversation (id, project_id, title) "
                           "VALUES ('c1', 'p', 't')"))
        bak = db.with_name(db.name + ".pre-migration.bak")
        assert not bak.exists()

        engine.ensure_columns()                 # missing 'pinned' etc. → back up, then ALTER

        assert bak.exists() and bak.stat().st_size > 0
        cols = {c["name"] for c in inspect(engine.get_engine()).get_columns("conversation")}
        assert "pinned" in cols and "owner_id" in cols   # the migration applied

        # The snapshot must be a valid, recoverable SQLite DB holding the PRE-migration
        # state: the original row, and the old schema (no 'pinned' yet).
        import sqlite3
        con = sqlite3.connect(bak)
        try:
            bak_cols = {r[1] for r in con.execute("PRAGMA table_info(conversation)")}
            assert "pinned" not in bak_cols            # snapshot predates the ALTER
            assert con.execute("SELECT id FROM conversation").fetchone()[0] == "c1"
        finally:
            con.close()
    finally:
        engine.reset_engine()


def test_no_backup_when_schema_is_current(monkeypatch, tmp_path):
    engine, db = _use_file_db(monkeypatch, tmp_path)
    try:
        engine.init_db()                        # creates the full current schema
        bak = db.with_name(db.name + ".pre-migration.bak")
        assert not bak.exists()                 # nothing pending → no snapshot
        engine.ensure_columns()                 # still a no-op
        assert not bak.exists()
    finally:
        engine.reset_engine()


def test_backup_is_a_noop_for_memory_db(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    from ocd_core.db import engine
    engine.reset_engine()
    try:
        engine.init_db()
        assert engine.backup_sqlite_before_migration() is None  # no file to snapshot
    finally:
        engine.reset_engine()
