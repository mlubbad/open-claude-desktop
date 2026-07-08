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


def get_engine():
    """Lazy singleton engine built from DATABASE_URL on first use."""
    global _engine
    if _engine is None:
        url = database_url()
        if url.startswith("sqlite"):
            kw = {"connect_args": {"check_same_thread": False}}
            if ":memory:" in url or url == "sqlite://":
                kw["poolclass"] = StaticPool
            _engine = create_engine(url, **kw)
        else:
            _engine = create_engine(url, pool_pre_ping=True)
    return _engine


def reset_engine() -> None:
    """Dispose + clear the cached engine (tests swap DATABASE_URL between cases)."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def init_db() -> None:
    """Create all tables from SQLModel metadata (dev/tests; prod uses Alembic)."""
    import ocd_core.db.models  # noqa: F401  register tables on the metadata
    SQLModel.metadata.create_all(get_engine())


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
