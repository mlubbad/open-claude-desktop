"""Sync SQLAlchemy/SQLModel engine + session lifecycle for ocd_core persistence.

The engine is LAZY (built on first use from DATABASE_URL) so importing this
module never opens a connection.

Local-first default: a SQLite file at a STABLE path derived from the package
location (config.REPO_ROOT), never from the process working directory — so the
app works out of the box on any machine, started from any directory, with zero
database setup. Postgres (or anything SQLAlchemy speaks) remains fully supported
by setting DATABASE_URL explicitly. In-memory SQLite uses StaticPool so every
Session shares one DB.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from .. import config


def _default_sqlite_url() -> str:
    # as_posix() keeps the URL well-formed on Windows (sqlite:///D:/... ) and
    # POSIX (sqlite:////home/... ) alike.
    return f"sqlite:///{(config.REPO_ROOT / 'ocd.db').as_posix()}"


DEFAULT_DATABASE_URL = _default_sqlite_url()

_engine = None


def database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


# SQLite defaults are hostile to a concurrent desktop app: the rollback journal
# takes a database-wide write lock and a second writer fails INSTANTLY with
# "database is locked" instead of waiting. The scheduler ticker, a live chat turn,
# and a Cowork task all write through the same file, so that race is routine.
# These pragmas fix it per connection:
#   journal_mode=WAL   — readers don't block the writer and vice-versa (file DBs).
#   busy_timeout=5000  — a blocked writer waits up to 5s for the lock instead of
#                        erroring immediately.
#   synchronous=NORMAL — safe with WAL, far fewer fsyncs (snappier writes).
#   foreign_keys=ON    — enforce any FK constraints (no-op for today's soft refs,
#                        correct the day a real FK is added).
_SQLITE_BUSY_TIMEOUT_MS = int(os.getenv("OCD_SQLITE_BUSY_TIMEOUT_MS", "5000"))


def _apply_sqlite_pragmas(dbapi_conn, _record, *, wal: bool) -> None:
    cur = dbapi_conn.cursor()
    try:
        if wal:  # WAL needs a real file; it's meaningless for :memory:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
        cur.execute("PRAGMA foreign_keys=ON")
    finally:
        cur.close()


def _build_engine(url: str):
    if url.startswith("sqlite"):
        kw = {"connect_args": {"check_same_thread": False}}
        in_memory = ":memory:" in url or url == "sqlite://"
        if in_memory:
            kw["poolclass"] = StaticPool
        eng = create_engine(url, **kw)
        # Run the pragmas on every new pooled connection (not just once): a file DB
        # opens many connections over its life and each needs them set.
        event.listen(eng, "connect",
                     lambda c, r: _apply_sqlite_pragmas(c, r, wal=not in_memory))
        return eng
    return create_engine(url, pool_pre_ping=True)


# When a configured (non-SQLite) DB is unreachable, we fall back to this URL so the
# app keeps working locally instead of 500-ing on every request. Set once by
# ensure_reachable(); get_engine() honours it thereafter.
_fallback_url: str | None = None


def get_engine():
    """Lazy singleton engine built from DATABASE_URL (or the local-SQLite fallback if
    the configured DB was found unreachable at startup)."""
    global _engine
    if _engine is None:
        _engine = _build_engine(_fallback_url or database_url())
    return _engine


def ensure_reachable() -> str | None:
    """Probe the configured database once; if it's a non-SQLite URL that can't be
    reached, fall back to the local SQLite default so persistence never hard-fails.

    Returns the fallback URL if a fallback happened, else None. Opt out by setting
    OCD_DB_FALLBACK=0 (a strict server deployment that should fail loudly instead).
    Local-first by default: a desktop user with a stale Postgres URL still gets a
    working app.
    """
    global _fallback_url
    url = database_url()
    if url.startswith("sqlite"):
        return None  # SQLite can't have an auth/network failure to fall back from
    if os.getenv("OCD_DB_FALLBACK", "1").strip().lower() in ("0", "false", "no"):
        return None
    try:
        eng = _build_engine(url)
        with eng.connect():
            pass
        eng.dispose()
        return None
    except Exception as e:  # unreachable / auth failure / driver missing
        import logging
        reset_engine()                       # clears _engine + any prior fallback
        _fallback_url = DEFAULT_DATABASE_URL  # next get_engine() builds local SQLite
        logging.getLogger("ocd").warning(
            "Database %s is unreachable (%s). Falling back to local SQLite at %s so the "
            "app keeps working. Fix DATABASE_URL or unset it to silence this; set "
            "OCD_DB_FALLBACK=0 to fail instead.",
            url.split("@")[-1], str(e).splitlines()[0][:200], DEFAULT_DATABASE_URL,
        )
        return _fallback_url


def reset_engine() -> None:
    """Dispose + clear the cached engine + any fallback (tests swap DATABASE_URL between cases)."""
    global _engine, _fallback_url
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _fallback_url = None


def init_db() -> None:
    """Create all tables from SQLModel metadata (dev/tests; prod uses Alembic)."""
    import ocd_core.db.models  # noqa: F401  register tables on the metadata
    SQLModel.metadata.create_all(get_engine())
    ensure_columns()


# New columns added to existing tables over time. create_all() only creates missing
# TABLES, never missing columns, so an existing local DB (SQLite or Postgres) would be
# missing these. This idempotent, dialect-agnostic check ALTERs in anything absent —
# simpler and safer for the local-first default than requiring an Alembic run.
_ADDED_COLUMNS = {
    "project": {
        "description": "VARCHAR",
        "pinned": "BOOLEAN DEFAULT 0",
        "archived": "BOOLEAN DEFAULT 0",
        "owner_id": "VARCHAR",
        "workspace_id": "VARCHAR",
    },
    "conversation": {
        "pinned": "BOOLEAN DEFAULT 0",
        "parent_id": "VARCHAR",
        "fork_index": "INTEGER",
        "owner_id": "VARCHAR",
        "workspace_id": "VARCHAR",
    },
}


def _sqlite_file_path():
    """On-disk path of the active SQLite DB, or None for in-memory / non-SQLite."""
    from pathlib import Path
    eng = get_engine()
    if not str(eng.url).startswith("sqlite"):
        return None
    db = eng.url.database
    if not db or db == ":memory:":
        return None
    return Path(db)


def backup_sqlite_before_migration():
    """Snapshot the SQLite DB before a schema change, so a botched ALTER is recoverable.

    Uses ``VACUUM INTO`` for a consistent copy that INCLUDES any WAL content (a plain
    file copy can miss it). Best-effort: a backup failure must never block startup.
    Returns the backup path if one was written, else None.
    """
    p = _sqlite_file_path()
    if not (p and p.exists() and p.stat().st_size > 0):
        return None
    bak = p.with_name(p.name + ".pre-migration.bak")
    try:
        if bak.exists():
            bak.unlink()
        target = bak.as_posix().replace("'", "''")  # VACUUM INTO takes no bind params
        with get_engine().connect() as conn:
            conn.exec_driver_sql(f"VACUUM INTO '{target}'")
        return bak
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("pre-migration DB backup skipped: %s", e)
        return None


def ensure_columns() -> None:
    from sqlalchemy import inspect, text
    eng = get_engine()
    try:
        insp = inspect(eng)
        tables = set(insp.get_table_names())
        # Collect what's missing FIRST so we only back up + ALTER when a migration is
        # actually needed (this runs on every startup; a no-op must stay cheap).
        pending = []  # (table, name, ddl)
        for table, cols in _ADDED_COLUMNS.items():
            if table not in tables:
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            pending += [(table, name, ddl) for name, ddl in cols.items()
                        if name not in existing]
        if not pending:
            return
        backup_sqlite_before_migration()  # existing data at risk → snapshot it first
        with eng.begin() as conn:
            for table, name, ddl in pending:
                conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {name} {ddl}'))
    except Exception as e:  # never let a best-effort migration break startup
        import logging
        logging.getLogger(__name__).warning("ensure_columns skipped: %s", e)


@contextmanager
def session() -> Iterator[Session]:
    """Transaction-scoped session: commit on clean exit, rollback on error, always close.

    Callers MUST extract any data into plain dicts INSIDE the `with` block --
    ORM objects are detached after the session closes. expire_on_commit is
    disabled so already-loaded scalar attributes remain readable post-commit.
    """
    s = Session(get_engine(), expire_on_commit=False)
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
