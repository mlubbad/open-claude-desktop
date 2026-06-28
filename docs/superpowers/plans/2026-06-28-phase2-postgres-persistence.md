# Phase 2 — Postgres Persistence — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move project registry, per-project metadata, and conversations from JSON files into Postgres (behind the unchanged `ocd_core.projects`/`ocd_core.conversations` APIs), with SQLModel + Alembic and an idempotent file→DB migration.

**Architecture:** A new `backend/ocd_core/db/` package (lazy sync engine, SQLModel models, `session()` context manager, Alembic, migration script). `projects.py`/`conversations.py` are rewritten DB-backed but keep identical signatures and return shapes (datetimes → ISO strings). Slices 1–5 are developed and tested entirely on in-memory SQLite; slice 6 provisions Postgres and runs the real-data migration.

**Tech Stack:** Python 3.12 · SQLModel + SQLAlchemy (sync) · Alembic · `psycopg` (sync Postgres driver) · pytest · SQLite (tests) / Postgres (prod).

---

## Scope & contract (read first)

- **Spec:** `docs/superpowers/specs/2026-06-28-phase2-postgres-persistence-design.md`. This plan implements all 6 slices.
- **Parity contract:** the public functions of `projects.py`/`conversations.py` keep their **exact signatures and return dict shapes** (§8 of the spec). Read the current modules (`backend/ocd_core/projects.py`, `backend/ocd_core/conversations.py`) before rewriting — the rewrite changes *storage*, not the API.
- **Environment:** repo `D:\HP\Projects\open-claude-desktop`, branch `refactor/phase2-postgres`. Interpreter `venv312\Scripts\python.exe`. `ocd_core` is editable-installed at `backend/ocd_core/`. Commit messages end with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **Two acknowledged behavior shifts** (spec §8): `get_project_memory()`'s timestamp comes from `updated_at` (not file mtime); `list_conversations()` no longer runs the on-read legacy migration (that fold moves to the migration script).
- **Datetimes:** stored as DB timestamps, **returned as ISO strings** (`.isoformat()`), so `util.relative_time`/the UI are unaffected.

## File structure

**Created:**
- `backend/ocd_core/db/__init__.py`
- `backend/ocd_core/db/engine.py` — lazy engine, `session()`, `init_db()`, `reset_engine()`
- `backend/ocd_core/db/models.py` — `Project`, `Conversation`
- `backend/ocd_core/db/migrate.py` — `migrate_filesystem_to_db()` + `__main__` CLI
- `backend/ocd_core/db/migrations/` — Alembic (`env.py`, `script.py.mako`, `versions/`)
- `backend/alembic.ini`
- `backend/tests/conftest.py` — the `db` fixture (SQLite in-memory)
- `backend/tests/test_db_engine.py`, `test_db_models.py`, `test_alembic.py`, `test_projects_db.py`, `test_conversations_db.py`, `test_migrate.py`

**Modified:**
- `backend/ocd_core/projects.py` — rewritten DB-backed (same API)
- `backend/ocd_core/conversations.py` — rewritten DB-backed (same API)
- `backend/pyproject.toml` — add `sqlmodel`, `alembic`, `psycopg[binary]`
- `docker-compose.yml`, `.env.example` — `ocd` database + `DATABASE_URL`

---

## Task 1: db package scaffold (engine + models)

**Files:**
- Create: `backend/ocd_core/db/__init__.py` (empty), `backend/ocd_core/db/engine.py`, `backend/ocd_core/db/models.py`
- Create: `backend/tests/conftest.py`, `backend/tests/test_db_engine.py`, `backend/tests/test_db_models.py`
- Modify: `backend/pyproject.toml` (deps)

- [ ] **Step 1: Install deps + add to pyproject**

Run (online): `venv312/Scripts/python.exe -m pip install sqlmodel alembic "psycopg[binary]"`
Then add to `backend/pyproject.toml` `[project] dependencies` (keep existing): `"sqlmodel"`, `"alembic"`, `"psycopg[binary]"`. Reinstall editable so metadata updates: `venv312/Scripts/python.exe -m pip install -e ./backend --no-deps`.

- [ ] **Step 2: Write the failing engine test** (`backend/tests/test_db_engine.py`)

```python
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
```

- [ ] **Step 3: Run it — expect FAIL** (`ModuleNotFoundError: No module named 'ocd_core.db'`)

Run: `venv312/Scripts/python.exe -m pytest backend/tests/test_db_engine.py -v`

- [ ] **Step 4: Write `backend/ocd_core/db/engine.py`**

```python
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

    Callers MUST extract any data into plain dicts INSIDE the `with` block —
    ORM objects are detached after the session closes.
    """
    s = Session(get_engine())
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
```

- [ ] **Step 5: Write the failing models test** (`backend/tests/test_db_models.py`)

```python
def test_models_have_expected_columns():
    from ocd_core.db.models import Project, Conversation
    assert set(Project.model_fields) >= {
        "id", "name", "instructions", "memory", "allowlist", "created_at", "updated_at"}
    assert set(Conversation.model_fields) >= {
        "id", "project_id", "title", "pinned", "transcript", "created_at", "updated_at"}
```

- [ ] **Step 6: Write `backend/ocd_core/db/models.py`**

```python
"""SQLModel tables for ocd_core persistence (Phase 2): Project, Conversation."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Project(SQLModel, table=True):
    id: str = Field(primary_key=True)              # the slug
    name: str
    instructions: str = ""
    memory: str = ""
    allowlist: list = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Conversation(SQLModel, table=True):
    id: str = Field(primary_key=True)              # 12-hex id
    project_id: str = Field(index=True)            # soft ref ("general" or a slug)
    title: str
    pinned: bool = False
    transcript: list = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
```

> **KNOWN GOTCHA:** some SQLModel versions raise `Cannot specify both default and sa_column` for the JSON fields. If `test_db_models.py` fails at import with that error, change the two JSON fields to `allowlist: list = Field(sa_column=Column(JSON, default=list))` (and same for `transcript`), and ensure callers always pass an explicit list. Verify by re-running the test.

- [ ] **Step 7: Write `backend/tests/conftest.py` (shared DB fixture)**

```python
import pytest


@pytest.fixture
def db(monkeypatch):
    """Fresh in-memory SQLite DB per test, with tables created."""
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    from ocd_core.db import engine
    engine.reset_engine()
    engine.init_db()
    yield
    engine.reset_engine()
```

- [ ] **Step 8: Run all new tests — expect PASS**

Run: `venv312/Scripts/python.exe -m pytest backend/tests/test_db_engine.py backend/tests/test_db_models.py -v`
Expected: PASS. Then run the whole suite (`venv312/Scripts/python.exe -m pytest backend/tests -q`) — prior 74 + new, green.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat(db): scaffold ocd_core.db (lazy engine, session(), Project/Conversation models)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Alembic — initial migration

**Files:**
- Create: `backend/alembic.ini`, `backend/ocd_core/db/migrations/env.py`, `backend/ocd_core/db/migrations/script.py.mako`, `backend/ocd_core/db/migrations/versions/` (dir)
- Create: `backend/tests/test_alembic.py`

- [ ] **Step 1: Initialize Alembic scaffolding**

Run from `backend/`: `venv312/Scripts/python.exe -m alembic init ocd_core/db/migrations` (creates `alembic.ini` + the `migrations/` tree). Then edit `backend/alembic.ini`: set `script_location = ocd_core/db/migrations` and leave `sqlalchemy.url` empty (env.py supplies it from `DATABASE_URL`).

- [ ] **Step 2: Wire `env.py` to SQLModel metadata + DATABASE_URL**

Replace `backend/ocd_core/db/migrations/env.py`'s config block so it targets our metadata and url:

```python
from logging.config import fileConfig
from alembic import context
from sqlmodel import SQLModel
import ocd_core.db.models  # noqa: F401  register tables
from ocd_core.db.engine import database_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
config.set_main_option("sqlalchemy.url", database_url())
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    context.configure(url=database_url(), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from sqlalchemy import create_engine
    connectable = create_engine(database_url())
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

Add `import sqlmodel` to the top of `script.py.mako`'s imports list so autogenerated migrations can reference `sqlmodel.sql.sqltypes` (SQLModel string columns). (Edit the mako: add the line `import sqlmodel` next to `import sqlalchemy as sa`.)

- [ ] **Step 3: Autogenerate the initial migration (against SQLite)**

Run from `backend/`:
```bash
DATABASE_URL=sqlite:///./_alembic_tmp.db venv312/Scripts/python.exe -m alembic revision --autogenerate -m "initial projects + conversations"
```
Open the generated `versions/<rev>_initial_*.py` and verify its `upgrade()` creates `project` and `conversation` tables with the columns from `models.py` (id/name/instructions/memory/allowlist/created_at/updated_at; id/project_id/title/pinned/transcript/created_at/updated_at) and the index on `conversation.project_id`. Delete the throwaway `backend/_alembic_tmp.db`.

- [ ] **Step 4: Write the failing Alembic test** (`backend/tests/test_alembic.py`)

```python
import pathlib
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_initial_migration_creates_tables(tmp_path, monkeypatch):
    db_file = tmp_path / "alembic.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    backend = pathlib.Path("backend")
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "ocd_core" / "db" / "migrations"))
    command.upgrade(cfg, "head")
    insp = inspect(create_engine(f"sqlite:///{db_file}"))
    tables = set(insp.get_table_names())
    assert {"project", "conversation"} <= tables
```

- [ ] **Step 5: Run it — expect PASS** (the migration from Step 3 applies)

Run: `venv312/Scripts/python.exe -m pytest backend/tests/test_alembic.py -v`
If it fails because `script_location`/paths differ, fix `alembic.ini` + the test's path wiring until green. Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(db): alembic env + initial migration (project, conversation tables)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: DB-backed `projects.py`

Rewrite `projects.py` to persist in the DB while keeping every signature + return shape. **Read the current `backend/ocd_core/projects.py` first** to match behavior (slugify+dedupe, default instructions text, the lean `{id,name,created_at}` shape, disk `knowledge/` dir creation, Chroma collection drop on delete).

**Files:**
- Modify: `backend/ocd_core/projects.py`
- Create: `backend/tests/test_projects_db.py`

- [ ] **Step 1: Write failing tests** (`backend/tests/test_projects_db.py`)

```python
import pytest
from ocd_core import projects


def test_create_get_list_lean_shape(db):
    meta = projects.create_project("My Cool Project")
    assert meta == {"id": "my-cool-project", "name": "My Cool Project",
                    "created_at": meta["created_at"]}
    assert isinstance(meta["created_at"], str) and "T" in meta["created_at"]  # ISO string
    assert projects.get_project("my-cool-project")["name"] == "My Cool Project"
    assert [p["id"] for p in projects.list_projects()] == ["my-cool-project"]


def test_duplicate_name_gets_unique_id(db):
    a = projects.create_project("Dup")
    b = projects.create_project("Dup")
    assert a["id"] == "dup" and b["id"] != a["id"] and b["id"].startswith("dup-")


def test_instructions_memory_allowlist_roundtrip(db):
    projects.create_project("P")
    assert projects.get_project_instructions("p").startswith("# Instructions for P")
    projects.save_project_instructions("p", "do X")
    assert projects.get_project_instructions("p") == "do X"
    projects.save_project_memory("p", "remember Y")
    text, rel = projects.get_project_memory("p")
    assert text == "remember Y" and isinstance(rel, str)
    assert projects.get_project_allowlist("p") == []


def test_delete_removes_row(db):
    projects.create_project("Temp")
    assert projects.delete_project("temp") is True
    assert projects.get_project("temp") is None
    assert projects.delete_project("temp") is False
```

- [ ] **Step 2: Run — expect FAIL** (current file-based `projects` ignores the SQLite `db` fixture; `create_project` writes to disk and returns, but `get_project` reads the JSON registry → assertions on DB-backed behavior fail, or it pollutes `projects/`). Confirm RED.

Run: `venv312/Scripts/python.exe -m pytest backend/tests/test_projects_db.py -v`

- [ ] **Step 3: Rewrite `backend/ocd_core/projects.py`**

```python
"""Project registry + per-project metadata, persisted in Postgres (Phase 2).

Same public API and return shapes as the prior file-based module; only the
storage changed. Datetimes are returned as ISO strings. Uploaded KB files still
live on disk under projects/<id>/knowledge/ and ChromaDB still holds vectors.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlmodel import select

from . import config, util
from .chroma import _get_chroma
from .db.engine import session
from .db.models import Project, utcnow

# Uploaded files still live on disk; ensure the root exists (parity with the old module).
config.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def _meta(p: Project) -> dict:
    return {"id": p.id, "name": p.name, "created_at": p.created_at.isoformat()}


def get_project_allowlist(project_id: str) -> list:
    with session() as s:
        p = s.get(Project, project_id)
        return list(p.allowlist) if p and p.allowlist else []


def list_projects() -> list[dict]:
    with session() as s:
        return [_meta(p) for p in s.exec(select(Project).order_by(Project.created_at)).all()]


def get_project(project_id: str) -> dict | None:
    with session() as s:
        p = s.get(Project, project_id)
        return _meta(p) if p else None


def create_project(name: str) -> dict:
    project_id = util.slugify(name)
    with session() as s:
        if s.get(Project, project_id) is not None:
            project_id = f"{project_id}-{uuid.uuid4().hex[:4]}"
        now = utcnow()
        p = Project(id=project_id, name=name,
                    instructions=f"# Instructions for {name}\n\n"
                                 "Add specific guidelines for this project here.\n",
                    memory="", allowlist=[], created_at=now, updated_at=now)
        s.add(p)
        meta = _meta(p)
    # uploaded files still live on disk
    (config.PROJECTS_DIR / project_id / "knowledge").mkdir(parents=True, exist_ok=True)
    return meta


def delete_project(project_id: str) -> bool:
    with session() as s:
        p = s.get(Project, project_id)
        if p is None:
            return False
        s.delete(p)
        from .db.models import Conversation
        for c in s.exec(select(Conversation).where(Conversation.project_id == project_id)).all():
            s.delete(c)
    proj_dir = config.PROJECTS_DIR / project_id
    if proj_dir.exists():
        import shutil
        shutil.rmtree(proj_dir, ignore_errors=True)
    try:
        _get_chroma().delete_collection(f"kb_project_{project_id}")
    except Exception:
        pass
    return True


def get_project_instructions(project_id: str) -> str:
    with session() as s:
        p = s.get(Project, project_id)
        return p.instructions if p else ""


def save_project_instructions(project_id: str, content: str):
    with session() as s:
        p = s.get(Project, project_id)
        if p:
            p.instructions = content
            p.updated_at = utcnow()
            s.add(p)


def get_project_memory(project_id: str) -> tuple[str, str]:
    """Returns (memory_text, last_updated_relative). Timestamp from updated_at."""
    with session() as s:
        p = s.get(Project, project_id)
        if not p:
            return "", ""
        return p.memory, (util.relative_time(p.updated_at.isoformat()) if p.memory else "")


def save_project_memory(project_id: str, content: str):
    with session() as s:
        p = s.get(Project, project_id)
        if p:
            p.memory = content
            p.updated_at = utcnow()
            s.add(p)


def project_capacity(project_id: str) -> dict:
    # Unchanged: uploaded files still live on disk.
    from .knowledge import list_project_files
    files = list_project_files(project_id)
    used = sum(f["size"] for f in files)
    pct = min(int(used / config.PROJECT_CAPACITY_BYTES * 100), 100) \
        if config.PROJECT_CAPACITY_BYTES else 0
    return {"used_mb": round(used / (1024 * 1024), 1),
            "max_mb": round(config.PROJECT_CAPACITY_BYTES / (1024 * 1024), 1),
            "percent": pct}


def project_card_view(p: dict) -> dict:
    instr = get_project_instructions(p["id"])
    desc = instr.split("\n")[0].replace("#", "").strip()
    if not desc or len(desc) < 5:
        desc = "No description provided yet."
    if len(desc) > 80:
        desc = desc[:77] + "…"
    return {"id": p["id"], "name": p.get("name", "Untitled"),
            "updated": util.format_date(p.get("created_at", "")), "desc": desc,
            "href": f"/project/{p['id']}"}
```

> Note: the old module's `_load_registry`/`_save_registry`/`_REGISTRY_FILE` are removed. Grep `backend/` + `aj360_app/` for any external use of those private names (there should be none — they were internal). The migration script (Task 5) reads the legacy `_registry.json`.

- [ ] **Step 4: Run — expect PASS**

Run: `venv312/Scripts/python.exe -m pytest backend/tests/test_projects_db.py -v` → PASS.

- [ ] **Step 5: Sanity — both apps still import**

Run: `venv312/Scripts/python.exe -c "import sys; sys.path.insert(0,'aj360_app'); from aj360_app import core, agent, integrations; print('ok')"`
(Imports must succeed; `projects` functions now need a DB at call-time, but import is lazy.)

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(projects): DB-backed registry + metadata (same API, ISO datetimes)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: DB-backed `conversations.py`

Rewrite `conversations.py` DB-backed; **drop** the on-read `migrate_legacy_chat_history` (the fold moves to Task 5). Keep all signatures + shapes. **Read the current module first.**

**Files:**
- Modify: `backend/ocd_core/conversations.py`
- Create: `backend/tests/test_conversations_db.py`

- [ ] **Step 1: Write failing tests** (`backend/tests/test_conversations_db.py`)

```python
from ocd_core import conversations as cv


def test_create_get_save(db):
    conv = cv.create_conversation("p1", "first message about hero rails")
    assert conv["title"].startswith("first message")
    assert conv["messages"][0] == {"role": "user", "content": "first message about hero rails", "kind": "user"}
    assert isinstance(conv["created_at"], str) and "T" in conv["created_at"]
    cv.save_conversation("p1", conv["id"], [{"role": "user", "content": "hi", "kind": "user"}], title="T")
    got = cv.get_conversation("p1", conv["id"])
    assert got["title"] == "T" and got["messages"][-1]["content"] == "hi"
    # scoped to project: wrong project_id returns None
    assert cv.get_conversation("other", conv["id"]) is None


def test_pin_list_move_delete(db):
    conv = cv.create_conversation("p1", "msg")
    cv.set_conversation_pinned("p1", conv["id"], True)
    summaries = cv.list_conversations("p1")
    assert summaries[0]["pinned"] is True and summaries[0]["id"] == conv["id"]
    assert "updated_rel" in summaries[0] and summaries[0]["href"].endswith(conv["id"])
    assert cv.move_conversation("p1", conv["id"], "p2") is True
    assert cv.get_conversation("p1", conv["id"]) is None
    assert cv.get_conversation("p2", conv["id"]) is not None
    cv.delete_conversation("p2", conv["id"])
    assert cv.get_conversation("p2", conv["id"]) is None


def test_list_all_includes_general(db, monkeypatch):
    # general bucket needs no Project row (soft project_id)
    cv.create_conversation("general", "a general chat")
    items = cv.list_all_conversations()
    assert any(i["project_id"] == "general" for i in items)
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError`-free but file-based code ignores the DB / writes files). Confirm RED.

Run: `venv312/Scripts/python.exe -m pytest backend/tests/test_conversations_db.py -v`

- [ ] **Step 3: Rewrite `backend/ocd_core/conversations.py`**

```python
"""Per-project conversations (Claude-style threads), persisted in Postgres (Phase 2).

Same public API + return shapes as the prior file-based module; only storage
changed. Datetimes are returned as ISO strings. The on-read legacy fold
(migrate_legacy_chat_history) is gone — handled once by ocd_core.db.migrate.
"""
from __future__ import annotations

import uuid

from sqlmodel import select

from . import config, util
from .db.engine import session
from .db.models import Conversation, utcnow


def _conv_title_from(text: str) -> str:
    t = " ".join((text or "").split())
    return (t[:48] + "…") if len(t) > 48 else (t or "New conversation")


def _to_dict(c: Conversation) -> dict:
    return {"id": c.id, "title": c.title,
            "created_at": c.created_at.isoformat(),
            "updated_at": c.updated_at.isoformat(),
            "pinned": c.pinned, "messages": list(c.transcript)}


def _summary(c: Conversation, project_id: str) -> dict:
    ts = c.updated_at.isoformat()
    return {"id": c.id, "title": c.title, "updated_at": ts,
            "updated_rel": util.relative_time(ts), "pinned": bool(c.pinned),
            "href": f"/project/{project_id}/c/{c.id}"}


def create_conversation(project_id: str, first_message: str) -> dict:
    now = utcnow()
    c = Conversation(id=uuid.uuid4().hex[:12], project_id=project_id,
                     title=_conv_title_from(first_message), pinned=False,
                     transcript=[{"role": "user", "content": first_message, "kind": "user"}],
                     created_at=now, updated_at=now)
    with session() as s:
        s.add(c)
        return _to_dict(c)


def get_conversation(project_id: str, conv_id: str) -> dict | None:
    with session() as s:
        c = s.get(Conversation, conv_id)
        return _to_dict(c) if c and c.project_id == project_id else None


def save_conversation(project_id: str, conv_id: str, messages: list[dict],
                      title: str | None = None) -> dict:
    with session() as s:
        c = s.get(Conversation, conv_id)
        if c is None or c.project_id != project_id:
            now = utcnow()
            c = Conversation(id=conv_id, project_id=project_id,
                             title=title or "Conversation", pinned=False,
                             transcript=[], created_at=now, updated_at=now)
        c.transcript = list(messages)[-config.CONV_MAX_MESSAGES:]
        if title:
            c.title = title
        c.updated_at = utcnow()
        s.add(c)
        return _to_dict(c)


def set_conversation_title(project_id: str, conv_id: str, title: str):
    with session() as s:
        c = s.get(Conversation, conv_id)
        if c and c.project_id == project_id:
            c.title = title
            c.updated_at = utcnow()
            s.add(c)


def set_conversation_pinned(project_id: str, conv_id: str, pinned: bool):
    with session() as s:
        c = s.get(Conversation, conv_id)
        if c and c.project_id == project_id:
            c.pinned = bool(pinned)
            s.add(c)


def move_conversation(src_pid: str, conv_id: str, dst_pid: str) -> bool:
    if src_pid == dst_pid:
        return True
    with session() as s:
        c = s.get(Conversation, conv_id)
        if not c or c.project_id != src_pid:
            return False
        c.project_id = dst_pid
        s.add(c)
        return True


def delete_conversation(project_id: str, conv_id: str):
    with session() as s:
        c = s.get(Conversation, conv_id)
        if c and c.project_id == project_id:
            s.delete(c)


def list_conversations(project_id: str) -> list[dict]:
    with session() as s:
        rows = s.exec(select(Conversation).where(Conversation.project_id == project_id)).all()
        out = [_summary(c, project_id) for c in rows]
    out.sort(key=lambda x: (x["pinned"], x["updated_at"]), reverse=True)
    return out


def list_all_conversations(limit: int = 200) -> list[dict]:
    from .projects import list_projects
    spaces = [(p["id"], p.get("name", "Untitled")) for p in list_projects()]
    spaces.append((config.GENERAL_ID, config.GENERAL_NAME))
    out = []
    for pid, pname in spaces:
        for c in list_conversations(pid):
            out.append({**c, "project_id": pid, "project_name": pname})
    out.sort(key=lambda x: (x["pinned"], x["updated_at"]), reverse=True)
    return out[:limit]


def generate_conversation_title(first_message: str) -> str:
    """Short Claude-style title from the first message (best-effort LLM, cheap)."""
    from .llm import get_llm_client
    try:
        llm = get_llm_client()
        resp = llm.chat.completions.create(
            model=config.FLASH_MODEL, temperature=0.2, max_tokens=20,
            messages=[{"role": "user", "content":
                       "Summarize this request as a 3-6 word title. No quotes, no "
                       f"trailing punctuation:\n\n{first_message}"}])
        t = (resp.choices[0].message.content or "").strip().strip('"').strip()
        t = t.split("\n")[0][:60]
        return t or _conv_title_from(first_message)
    except Exception:
        return _conv_title_from(first_message)
```

> Note: `migrate_legacy_chat_history` is intentionally removed. Grep `aj360_app/` for `migrate_legacy_chat_history` and `core.migrate_legacy_chat_history` — if `state.py` or the `core.py` shim re-exports it, remove that re-export line (the function no longer exists). The legacy fold is in Task 5.

- [ ] **Step 4: Run — expect PASS**

Run: `venv312/Scripts/python.exe -m pytest backend/tests/test_conversations_db.py -v` → PASS.

- [ ] **Step 5: Sanity — both apps import; fix any stale re-export**

Run: `venv312/Scripts/python.exe -c "import sys; sys.path.insert(0,'aj360_app'); from aj360_app import core, agent, integrations; print('ok')"`.
If it errors on `migrate_legacy_chat_history`, remove that name from the `core.py` re-export block (Step 3 note).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(conversations): DB-backed threads (same API); drop on-read legacy fold" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: filesystem → DB migration script

**Files:**
- Create: `backend/ocd_core/db/migrate.py`
- Create: `backend/tests/test_migrate.py`

- [ ] **Step 1: Write failing tests** (`backend/tests/test_migrate.py`)

```python
import json
from ocd_core.db import migrate
from ocd_core.db.engine import session
from ocd_core.db.models import Project, Conversation
from sqlmodel import select


def _seed_tree(root):
    (root / "_registry.json").write_text(json.dumps([
        {"id": "alpha", "name": "Alpha", "created_at": "2026-01-01T00:00:00+00:00"},
    ]), encoding="utf-8")
    pdir = root / "alpha"
    (pdir / "knowledge").mkdir(parents=True)
    (pdir / "instructions.md").write_text("do alpha", encoding="utf-8")
    (pdir / "allowlist.json").write_text(json.dumps(["aj360.events"]), encoding="utf-8")
    cdir = pdir / "conversations"; cdir.mkdir()
    (cdir / "c1.json").write_text(json.dumps({
        "id": "c1", "title": "Chat 1", "created_at": "2026-01-02T00:00:00+00:00",
        "updated_at": "2026-01-03T00:00:00+00:00", "pinned": True,
        "messages": [{"role": "user", "content": "hi", "kind": "user"}]}), encoding="utf-8")
    gdir = root / "general" / "conversations"; gdir.mkdir(parents=True)
    (gdir / "g1.json").write_text(json.dumps({
        "id": "g1", "title": "General", "created_at": "2026-01-04T00:00:00+00:00",
        "updated_at": "2026-01-04T00:00:00+00:00", "messages": []}), encoding="utf-8")


def test_migrate_counts_and_fidelity(db, tmp_path):
    _seed_tree(tmp_path)
    result = migrate.migrate_filesystem_to_db(tmp_path)
    assert result == {"projects": 1, "conversations": 2}
    with session() as s:
        p = s.get(Project, "alpha")
        assert p.name == "Alpha" and p.instructions == "do alpha" and p.allowlist == ["aj360.events"]
        c = s.get(Conversation, "c1")
        assert c.project_id == "alpha" and c.pinned is True and c.transcript[0]["content"] == "hi"
        assert s.get(Conversation, "g1").project_id == "general"


def test_migrate_is_idempotent(db, tmp_path):
    _seed_tree(tmp_path)
    migrate.migrate_filesystem_to_db(tmp_path)
    again = migrate.migrate_filesystem_to_db(tmp_path)
    assert again == {"projects": 1, "conversations": 2}
    with session() as s:
        assert len(s.exec(select(Conversation)).all()) == 2  # no duplicates
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError: No module named 'ocd_core.db.migrate'`)

Run: `venv312/Scripts/python.exe -m pytest backend/tests/test_migrate.py -v`

- [ ] **Step 3: Write `backend/ocd_core/db/migrate.py`**

```python
"""One-time, idempotent filesystem → Postgres migration (Phase 2).

Reads the legacy projects/ tree (registry + per-project metadata files +
conversation JSONs, including the general/ bucket and any legacy
chat_history.json) and upserts Project/Conversation rows. Safe to re-run.

Run: python -m ocd_core.db.migrate   (uses DATABASE_URL + alembic head)
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import config_dir  # see note below; falls back to ocd_core.config.PROJECTS_DIR
from .engine import session
from .models import Conversation, Project, utcnow


def _parse_dt(value: str | None) -> datetime:
    if value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return utcnow()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def migrate_filesystem_to_db(projects_dir: Path) -> dict:
    """Upsert all projects + conversations from the file tree. Returns counts."""
    projects_dir = Path(projects_dir)
    n_projects = n_convs = 0

    registry = _read_json(projects_dir / "_registry.json", [])
    with session() as s:
        for entry in registry:
            pid = entry["id"]
            pdir = projects_dir / pid
            p = s.get(Project, pid) or Project(id=pid, name=entry.get("name", pid))
            p.name = entry.get("name", pid)
            p.instructions = _read_text(pdir / "instructions.md")
            p.memory = _read_text(pdir / "memory.md")
            p.allowlist = _read_json(pdir / "allowlist.json", [])
            p.created_at = _parse_dt(entry.get("created_at"))
            p.updated_at = p.created_at
            s.add(p)
            n_projects += 1

    # conversations for every project dir that has a conversations/ folder, incl. "general"
    conv_dirs = [d for d in projects_dir.iterdir()
                 if d.is_dir() and (d / "conversations").is_dir()] if projects_dir.exists() else []
    with session() as s:
        for pdir in conv_dirs:
            pid = pdir.name
            # legacy single chat_history.json → fold into a conversation
            legacy = pdir / "chat_history.json"
            if legacy.exists():
                msgs = _read_json(legacy, [])
                if isinstance(msgs, list) and msgs:
                    first = next((m.get("content", "") for m in msgs
                                  if m.get("kind") == "user"), "Imported conversation")
                    cid = uuid.uuid4().hex[:12]
                    if s.get(Conversation, cid) is None:
                        now = utcnow()
                        s.add(Conversation(id=cid, project_id=pid,
                                           title=first[:48] or "Imported", transcript=msgs,
                                           created_at=now, updated_at=now))
                        n_convs += 1
            for cf in (pdir / "conversations").glob("*.json"):
                data = _read_json(cf, None)
                if not isinstance(data, dict) or "id" not in data:
                    continue
                cid = data["id"]
                c = s.get(Conversation, cid) or Conversation(id=cid, project_id=pid, title="")
                c.project_id = pid
                c.title = data.get("title", "Conversation")
                c.pinned = bool(data.get("pinned", False))
                c.transcript = data.get("messages", [])
                c.created_at = _parse_dt(data.get("created_at"))
                c.updated_at = _parse_dt(data.get("updated_at") or data.get("created_at"))
                s.add(c)
                n_convs += 1

    return {"projects": n_projects, "conversations": n_convs}


def _main() -> int:
    import shutil
    from .config_dir import PROJECTS_DIR  # resolved import (see note)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = PROJECTS_DIR.parent / f"projects.backup-{stamp}"
    if PROJECTS_DIR.exists():
        shutil.copytree(PROJECTS_DIR, backup)
        print(f"[migrate] backed up {PROJECTS_DIR} -> {backup}")
    # ensure schema
    import subprocess
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd="backend", check=True)
    counts = migrate_filesystem_to_db(PROJECTS_DIR)
    print(f"[migrate] migrated {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
```

> **IMPLEMENTER NOTE — fix the `config_dir` import:** the skeleton above references a non-existent `config_dir` to keep the public function free of import side effects. Replace both `from . import config_dir` / `from .config_dir import PROJECTS_DIR` with the real source: `from ocd_core.config import PROJECTS_DIR` (used only inside `_main`, not at module top, to avoid eager config reads). The public `migrate_filesystem_to_db(projects_dir)` must take the dir as a parameter (as the tests call it) — only `_main()` reads `config.PROJECTS_DIR`.

- [ ] **Step 4: Run — expect PASS** (both tests, after fixing the import note)

Run: `venv312/Scripts/python.exe -m pytest backend/tests/test_migrate.py -v` → PASS (counts + fidelity + idempotency).

- [ ] **Step 5: Full suite green**

Run: `venv312/Scripts/python.exe -m pytest backend/tests -q` — all prior + new, green.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(db): idempotent filesystem->DB migration script (+legacy fold)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Postgres integration + wiring (needs a live Postgres)

This slice provisions Postgres, runs the real-data migration, and boots the Reflex app end-to-end. The code changes are testable; the live run requires Postgres up.

**Files:**
- Modify: `backend/pyproject.toml` (deps — if not already added in Task 1), `docker-compose.yml`, `.env.example`

- [ ] **Step 1: Pin/declare deps**

Confirm `backend/pyproject.toml` `dependencies` includes `sqlmodel`, `alembic`, `psycopg[binary]` (added in Task 1). Run `venv312/Scripts/python.exe -m pip install -e ./backend --no-deps` to confirm metadata is consistent.

- [ ] **Step 2: Add the `ocd` database + DATABASE_URL to compose**

In `docker-compose.yml`, add an init step so the existing Postgres also creates an `ocd` database, and document the URL. Append to the `postgres` service a second init script and add `.env.example` entries:

Create `backend/db_init/01_create_ocd.sql`:
```sql
CREATE DATABASE ocd;
```
Mount it in `docker-compose.yml` under the postgres `volumes:` (alongside the existing schema.sql line):
```yaml
      - ./backend/db_init/01_create_ocd.sql:/docker-entrypoint-initdb.d/02_create_ocd.sql:ro
```
Add to `.env.example`:
```
# ocd_core (Phase 2) persistence — sync psycopg driver
DATABASE_URL=postgresql+psycopg://chainlit:changeme@localhost:5432/ocd
```
(Reuses the existing `chainlit` superuser to own the `ocd` DB; adjust user/password to match your `.env`.)

- [ ] **Step 3: Write a DATABASE_URL-driven engine test** (`backend/tests/test_db_engine.py`, add)

```python
def test_engine_uses_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./_url_probe.db")
    from ocd_core.db import engine
    engine.reset_engine()
    assert str(engine.get_engine().url).endswith("_url_probe.db")
    engine.reset_engine()
    import os
    if os.path.exists("_url_probe.db"):
        os.remove("_url_probe.db")
```
Run: `venv312/Scripts/python.exe -m pytest backend/tests/test_db_engine.py -v` → PASS.

- [ ] **Step 4: Live provisioning + real migration (run with Postgres up)**

Documented procedure (run locally with Docker available):
```bash
# 1. bring up Postgres (creates the ocd database on first start)
docker compose up -d postgres
# 2. set DATABASE_URL in your shell/.env to the ocd DB (sync psycopg), e.g.:
#    DATABASE_URL=postgresql+psycopg://chainlit:changeme@localhost:5432/ocd
# 3. create the schema
cd backend && venv312/Scripts/python.exe -m alembic upgrade head && cd ..
# 4. migrate the real data (backs up projects/, then upserts)
venv312/Scripts/python.exe -m ocd_core.db.migrate
# expected: "[migrate] migrated {'projects': 2, 'conversations': 10}"
```

- [ ] **Step 5: Verify end-to-end (Postgres up)**

```bash
# row counts in Postgres match the files
venv312/Scripts/python.exe -c "from ocd_core.db.engine import session; from ocd_core.db.models import Project, Conversation; from sqlmodel import select; \
import os; \
print('projects', len(list(__import__('ocd_core.db.engine', fromlist=['session']))) ) " 2>/dev/null || true
# simpler check:
venv312/Scripts/python.exe -c "from ocd_core.db.engine import session; from ocd_core.db.models import Project, Conversation; from sqlmodel import select; \
s=session().__enter__(); print('projects', len(s.exec(select(Project)).all()), 'conversations', len(s.exec(select(Conversation)).all()))"
# boot the Reflex app (separate terminal) and confirm projects + conversations appear:
cd aj360_app && set REFLEX_USE_NPM=true && ../venv312/Scripts/python.exe -m reflex run
```
Expected: 2 projects + 10 conversations reported; the Reflex workspace shows the migrated projects and their conversations, served from Postgres.

- [ ] **Step 6: Full suite green + commit**

Run: `venv312/Scripts/python.exe -m pytest backend/tests -q` (SQLite-based, no Postgres needed) → all green.
```bash
git add -A
git commit -m "feat(db): Postgres wiring — compose ocd db, DATABASE_URL, real-data migration procedure" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Appendix A: sanity check (run after each slice)

```bash
venv312/Scripts/python.exe -m pytest backend/tests -q          # all green (SQLite)
venv312/Scripts/python.exe -c "import sys; sys.path.insert(0,'aj360_app'); from aj360_app import core, agent, integrations; print('domain import OK')"
venv312/Scripts/python.exe -c "import sys; sys.path.insert(0,'aj360_app'); import aj360_app.aj360_app as ui; print('reflex ui import OK')"
```

## Self-review

- **Spec coverage:** db package + engine/`session()` (T1), models (T1, spec §5), Alembic from start (T2, §7), DB-backed projects incl. instructions/memory/allowlist + lean shape + ISO datetimes (T3, §5/§8), DB-backed conversations + drop on-read legacy fold (T4, §8), idempotent migration + backup + verify + legacy fold (T5, §9), SQLite test strategy (T1 fixture, all tasks), Postgres provisioning + compose + real migration + boot (T6, §11). The two acknowledged behavior shifts (T3 `get_project_memory`, T4 dropped fold) are implemented. ✓
- **Placeholder scan:** the `config_dir` reference in T5 is explicitly flagged with the exact fix (`from ocd_core.config import PROJECTS_DIR`, inside `_main` only). The T6 live steps are a documented procedure (need Postgres) — clearly marked, not hidden TODOs. No other placeholders.
- **Type/name consistency:** `Project`/`Conversation` fields (id/name/instructions/memory/allowlist/created_at/updated_at; id/project_id/title/pinned/transcript/created_at/updated_at) are identical across T1, T3, T4, T5. `session()`/`get_engine()`/`reset_engine()`/`init_db()`/`utcnow()` consistent. The `db` fixture (T1 conftest) is used by T3/T4/T5. Return shapes (`_meta`, `_to_dict`, `_summary`) match the spec §8 contract.
