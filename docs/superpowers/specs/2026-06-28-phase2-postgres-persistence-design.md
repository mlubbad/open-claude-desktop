# Design: Phase 2 — Postgres Persistence (projects + conversations + metadata)

> **Date:** 2026-06-28 · **Status:** Draft for review
> **Parent:** `docs/superpowers/specs/2026-06-27-two-service-refactor-design.md` (§7). Phase 2 of 6.

## 1. Context

Phase 1 consolidated all domain logic into `backend/ocd_core/`. Today, project
and conversation state is **file-based**:

- `projects/_registry.json` — the project registry `[{id, name, created_at}]`.
- `projects/<id>/instructions.md`, `memory.md`, `allowlist.json` — per-project metadata.
- `projects/<id>/conversations/<cid>.json` — conversations
  `{id, title, created_at, updated_at, pinned?, messages:[{role, content, kind}]}`.
- `projects/<id>/knowledge/*` — **uploaded files** (real files).

This is read/written by `ocd_core/projects.py` and `ocd_core/conversations.py`.
Phase 2 moves the **relational metadata** into Postgres while keeping the exact
public API of those two modules, so every caller (`state.py`, `agent.py`) works
unchanged. There is real data to migrate on the current machine: **2 projects**
(`bigquery-4700`, `software-engineer`) + a `general` bucket, **10 conversations**.

## 2. Goals & non-goals

### Goals
1. Persist project registry, per-project metadata (instructions, memory,
   allowlist), and conversations in **Postgres** via **SQLModel/SQLAlchemy (sync)**.
2. **Preserve the public API exactly** — same function signatures AND same
   return dict shapes; no caller changes.
3. **Alembic** schema migrations from the start (one initial migration).
4. An **idempotent** filesystem→DB data migration that preserves the existing
   2 projects + 10 conversations, with backup + count verification.
5. Fast unit tests against **in-memory SQLite** (engine-swappable via SQLModel).

### Non-goals (YAGNI / later phases)
- No FastAPI / HTTP / SSE (Phase 3). The modules stay **synchronous**.
- No async DB driver — sync `psycopg` (Reflex calls these via `to_thread`).
- No normalized message table — the conversation `transcript` is a JSON column.
- Global `settings.json` stays a file — the parent spec's `Setting` table is
  **dropped as YAGNI** (one global row, not per-project metadata).
- Uploaded KB files (`projects/<id>/knowledge/*`) and ChromaDB stay on disk.
- No request-scoped session management (that arrives with FastAPI in Phase 3).

## 3. Locked decisions

| Decision | Choice |
|---|---|
| DB scope | Registry + conversations + **per-project metadata** (instructions/memory/allowlist) → Postgres |
| Test DB | **In-memory SQLite** (prod = Postgres; engine swappable via SQLModel) |
| Schema mgmt | **Alembic from the start** (one initial migration) |
| Driver / concurrency | **Sync** `psycopg` (preserve the synchronous module API) |
| `general` bucket | `project_id` is a **soft reference** (indexed string, no hard FK) — no phantom "General" Project row |
| Global settings | Stays `settings.json` (out of scope) |
| Uploaded files / vectors | Stay on disk / ChromaDB |

## 4. Architecture

New package `backend/ocd_core/db/`:

```
backend/ocd_core/db/
├─ __init__.py
├─ engine.py        # DATABASE_URL → lazy sync engine + Session helper
├─ models.py        # SQLModel tables: Project, Conversation
├─ migrate.py       # migrate_filesystem_to_db() + `python -m ocd_core.db.migrate`
└─ migrations/      # Alembic: env.py + versions/<initial>.py
backend/alembic.ini  # Alembic config (script_location → ocd_core/db/migrations)
```

`projects.py` and `conversations.py` are **rewritten to be DB-backed** behind
their existing API. `knowledge.py` (uploaded files) and `chroma.py` are
untouched. `project_capacity()` still reads file sizes from disk (uploaded files
remain there). `create_project()` still creates the on-disk `knowledge/` dir for
uploads, but writes its metadata to the DB instead of `instructions.md`.

## 5. Data model (SQLModel, sync)

```python
class Project(SQLModel, table=True):
    id: str = Field(primary_key=True)          # the slug, e.g. "bigquery-4700"
    name: str
    instructions: str = ""                      # was instructions.md
    memory: str = ""                            # was memory.md
    allowlist: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime
    updated_at: datetime

class Conversation(SQLModel, table=True):
    id: str = Field(primary_key=True)           # 12-hex id
    project_id: str = Field(index=True)         # soft ref ("general" or a slug); NOT an FK
    title: str
    pinned: bool = False
    transcript: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime
    updated_at: datetime
```

- `JSON` column type → JSONB on Postgres, JSON on SQLite (SQLModel/SQLAlchemy
  handles the dialect). `transcript` preserves the `{role, content, kind}` shape.
- `project_id` is indexed but **not FK-constrained**, so `"general"` and any slug
  work without a Project row — matching today's behavior where `list_projects()`
  excludes general.

## 6. Engine, session, config

- `engine.py` builds a **lazy** singleton engine from `DATABASE_URL` (created on
  first use, so importing the module never opens a connection). Default
  `DATABASE_URL` = the local Postgres (`postgresql+psycopg://ocd:ocd@localhost:5432/ocd`);
  tests set `DATABASE_URL=sqlite://…` before first use.
- A `session()` context manager yields `Session(engine)` and commits/closes —
  used per function call (mirrors today's load/save-per-call file pattern).
- Phase 3's FastAPI will introduce request-scoped sessions; not now.

## 7. Schema management (Alembic)

- `models.py` is the single schema source. Alembic `env.py` targets
  `SQLModel.metadata`; the initial migration is autogenerated and creates the
  `project` + `conversation` tables.
- `alembic upgrade head` provisions/upgrades the DB. **Unit tests** build the
  schema directly via `SQLModel.metadata.create_all(engine)` on SQLite (fast); a
  **separate** test asserts the Alembic migration applies cleanly (on SQLite, and
  on Postgres when `DATABASE_URL` is set) and yields the same tables.

## 8. Public API parity (the contract)

These signatures AND return shapes are preserved exactly. Datetimes are stored as
DB timestamps but **returned as ISO strings** (so `util.relative_time`/the UI are
unaffected).

**`projects.py`** — `list_projects()→[{id,name,created_at}]`,
`get_project(id)→{id,name,created_at}|None`, `create_project(name)→{id,name,created_at}`
(still makes the on-disk `knowledge/` dir; default instructions go to the DB
column), `delete_project(id)→bool` (DB row + on-disk dir + Chroma collection),
`get_project_instructions/save_project_instructions`, `get_project_memory→(text,rel)`,
`save_project_memory`, `get_project_allowlist→list`, `project_capacity→{used_mb,max_mb,percent}`
(unchanged — reads disk files), `project_card_view(p)→{...}`.

**`conversations.py`** — `create_conversation(pid,first)→conv`,
`get_conversation(pid,cid)→conv|None`, `save_conversation(pid,cid,messages,title=None)→conv`
(caps at `CONV_MAX_MESSAGES`), `set_conversation_title`, `set_conversation_pinned`,
`move_conversation(src,cid,dst)→bool`, `delete_conversation`,
`list_conversations(pid)→[{id,title,updated_at,updated_rel,pinned,href}]`,
`list_all_conversations(limit)→[…,project_id,project_name]`,
`generate_conversation_title(first)→str` (LLM — **unchanged**, storage-agnostic).

### Deliberate behavior shifts (acknowledged, non-blocking)
1. `get_project_memory()`'s "last updated" comes from the row's `updated_at`
   instead of the `memory.md` file mtime. Functionally equivalent.
2. `list_conversations()` no longer calls `migrate_legacy_chat_history()` on every
   read — the legacy `chat_history.json` fold is handled **once** by the data
   migration (§9). The runtime function is removed.

## 9. Data migration

`python -m ocd_core.db.migrate` — **idempotent** (upsert by primary key):
1. **Backup** the `projects/` tree to `projects.backup-<UTC-stamp>/` (files kept,
   never deleted).
2. `alembic upgrade head` (ensure schema exists).
3. For each `_registry.json` entry → upsert `Project(id, name, created_at,
   instructions=<instructions.md or default>, memory=<memory.md or "">,
   allowlist=<allowlist.json or []>, updated_at=created_at)`.
4. For each `projects/<id>/conversations/*.json` (including `general/`) → upsert
   `Conversation(id, project_id=<id>, title, pinned, transcript=<messages>,
   created_at, updated_at)`. Fold any legacy `chat_history.json` (the old
   `migrate_legacy_chat_history` logic) into a conversation here.
5. **Verify** row counts against file counts (expect 2 projects + 10
   conversations on the current machine) and report; non-zero mismatch → loud warning.

Idempotent re-runs are safe (existing rows are updated, not duplicated).

## 10. Testing strategy

- **Unit tests** (`backend/tests/`): an autouse fixture points `DATABASE_URL` at a
  SQLite engine (tmp-file or in-memory with `StaticPool` so sessions share state),
  runs `metadata.create_all`, and yields. Cover all `projects`/`conversations`
  CRUD + return-shape assertions (datetimes are ISO strings, lean `list_projects`
  shape, transcript fidelity, pin/move/delete, `list_all_conversations` cross-project + general).
- **Migration test**: build a fixture `projects/` tree (a couple of registry
  entries + instructions/memory/allowlist + conversation JSONs + a legacy
  `chat_history.json`), run `migrate_filesystem_to_db()`, assert row counts +
  field/transcript fidelity + idempotency (re-run → same counts).
- **Alembic test**: assert the initial migration applies on SQLite and produces
  the `project`/`conversation` tables matching `metadata`.
- **Optional Postgres integration test**: gated on a real `DATABASE_URL`.

## 11. Dependencies & compose

- Install into `venv312`: `sqlmodel`, `alembic`, `psycopg[binary]` (`sqlalchemy`
  already present). Add them to `backend/pyproject.toml` `dependencies`.
- `docker-compose.yml`: add an `ocd` database (init script on the existing
  Postgres, or a second DB) and document `DATABASE_URL=postgresql+psycopg://ocd:…@localhost:5432/ocd`.
- `.env.example`: add `DATABASE_URL`.

## 12. Implementation slices (high-level; detailed TDD plan follows)

1. **db scaffold** — install deps; `db/engine.py` (lazy engine + `session()`); `db/models.py` (Project, Conversation); a `create_all` smoke test on SQLite.
2. **Alembic init** — `alembic.ini` + `env.py` + initial autogenerated migration; test it applies on SQLite.
3. **DB-backed `projects.py`** — rewrite registry/instructions/memory/allowlist behind the same API; SQLite tests for parity of signatures + return shapes.
4. **DB-backed `conversations.py`** — rewrite conversation CRUD behind the same API; SQLite tests; drop the on-read legacy migration.
5. **Migration script** — `db/migrate.py` + CLI; fixture-tree test on SQLite (counts, fidelity, idempotency, legacy `chat_history.json` fold). Built and tested in isolation — does **not** require Postgres.
6. **Postgres integration + wiring** — deps in `backend/pyproject.toml`; compose `ocd` database + `DATABASE_URL` + `.env.example`; `alembic upgrade head` on Postgres; run `python -m ocd_core.db.migrate` against the **real** runtime files (verify the 2 projects + 10 conversations land in Postgres); boot the Reflex app against Postgres end-to-end; full suite green.

**Working-app guarantee:** slices 1–5 are developed and proven entirely against **SQLite** (the engine-swappable design makes this valid), so the test suite is green at every step. The cutover slices (3–4) change storage behind an unchanged API — verified by SQLite parity tests — and never run against an empty DB during testing because the fixtures seed their own rows. Real **Postgres** provisioning, the **real-data** migration, and the end-to-end Reflex-on-Postgres boot are consolidated into slice 6, consistent with the locked "Postgres-required for the app" decision. (`DATABASE_URL` defaults to local Postgres; the lazy engine means importing the modules and running the SQLite tests never needs a live Postgres.)

## 13. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Data loss in JSON→DB migration | Idempotent upsert; pre-backup of `projects/`; count + transcript verification; JSON kept as archive |
| Return-shape drift breaks `state.py` | §8 pins exact shapes; tests assert keys + ISO-string datetimes; both apps imported in verify |
| In-memory SQLite per-connection isolation | Test fixture uses tmp-file SQLite or `StaticPool` so sessions share one DB |
| Dev now requires Postgres up | Documented (accepted in the Phase-1 DB decision); lazy engine so imports/tests don't need a live DB; compose provides it |
| JSONB vs JSON dialect differences | Queries are simple (by id / project_id / order by updated_at) — no JSONB-only operators; SQLModel handles the column type per dialect |
| Sync `psycopg` vs Chainlit's `asyncpg` | Separate concerns; ocd_core uses sync; Chainlit's async layer is untouched and retired in Phase 5 |

## 14. Open questions

None blocking. Deferred by design: settings → DB (YAGNI), async sessions (Phase 3),
normalized message table, retiring the file-based archive after a confidence period.
