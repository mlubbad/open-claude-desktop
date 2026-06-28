"""Sync SQLAlchemy/SQLModel engine + session lifecycle for ocd_core persistence.

The engine is LAZY (built on first use from DATABASE_URL) so importing this
module never opens a connection. Prod default is local Postgres; tests inject
sqlite://. In-memory SQLite uses StaticPool so every Session shares one DB.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

DEFAULT_DATABASE_URL = "postgresql+psycopg://ocd:ocd@localhost:5432/ocd"

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
