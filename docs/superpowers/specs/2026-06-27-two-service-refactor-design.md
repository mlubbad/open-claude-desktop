# Design: Two-Service Refactor (FastAPI backend + Reflex frontend)

> **Date:** 2026-06-27 · **Status:** Draft for review
> **Supersedes the deferred items of** `docs/architecture-audit.md` (issues #3, #5, #7).

## 1. Context

The repo (`Open Claude Desktop`) is a GLM-powered, read-only BigQuery analytics
agent. Today it is **one Python monorepo with two UI frontends that duplicate
their domain logic**:

- **Chainlit chat** — `app.py`, a ~2,437-line god module (config, BigQuery,
  ChromaDB, projects, KB, agent loop, SQL execution, UI, auth, all in one file).
- **Reflex projects workspace** — `aj360_app/aj360_app/`, already cleanly split
  into a UI-agnostic domain layer (`core.py`, `agent.py`, `integrations.py`,
  `mcp_registry.py`) and a UI layer (`state.py`, `aj360_app.py`, `auth.py`).
- **`ocd_core/`** — a shared package whose extraction has only just begun
  (`sql_guard.py`, 61 lines).

The same domain logic — project registry, conversations, KB ingest, BigQuery
client, schema catalog, LLM client, agent loop — exists **twice** (once in
`app.py`, once in `aj360_app`'s domain modules). They share no code beyond
`sql_guard`; they only share files on disk (`projects/`, `knowledge/`,
`chroma_db/`). This is the divergence risk audit issue #3 flagged.

There is **no hand-written JavaScript/TypeScript frontend** — both UIs are pure
Python (Reflex compiles to React in the generated, gitignored `.web/`).

## 2. Goals & non-goals

### Goals
1. **One clear structure** with a single allowed separation: **backend** vs
   **frontend**, expressed as a monorepo with `backend/` and `frontend/`.
2. **Zero duplicated domain logic** — a single source of truth in `backend/ocd_core/`.
3. **A genuine service boundary** — the backend is an independently runnable
   FastAPI service; the frontend is a thin Reflex client that talks to it over
   HTTP + SSE.
4. **Behavior parity** — no feature regressions. Anything that lives only in the
   retired Chainlit app is salvaged into the backend first.
5. **A real persistence layer** — projects + conversations in Postgres (via
   SQLModel/SQLAlchemy + Alembic), migrated from today's JSON files.
6. **A `.claude/` config layer** so Claude Code maintains the repo well.
7. Close the deferred audit items: #3 (god module + duplication), #5 (tests via
   real imports), #7 (runtime/data layout).

### Non-goals (YAGNI)
- No redesign of the agent reasoning loop — it **moves**, it is not rewritten.
- No new product features; parity with current behavior is the bar.
- No multi-tenant RBAC beyond the existing single-user auth gate.
- No gRPC / message broker / queue — HTTP + SSE only.
- No Kubernetes — `docker compose` is the deploy target.
- No normalized per-message table initially — the conversation transcript is
  stored as a JSONB column for parity (can be normalized later).

## 3. Target architecture

Two services in one repo, communicating over HTTP (REST) + SSE (the agent
stream). The backend owns **all** domain logic and **all** data; the frontend
holds only UI state and renders.

```
Browser (Reflex-compiled React)
    │  Reflex websocket (internal to Reflex)
frontend/  — Reflex state server (thin client)
    │  HTTP + SSE   ◄── the new service boundary
backend/   — FastAPI  →  ocd_core (agent · sql_guard · projects · KB · schema)
    │
    ├─ BigQuery (read-only + cost guard)
    ├─ GLM / Zhipu (agent reasoning)
    ├─ ChromaDB (schema + KB vectors)      ── runtime/, owned by backend
    ├─ Postgres (projects + conversations)
    └─ MCP servers + REST connectors
```

### 3.1 The boundary protocol
- **Agent turns** stream over **SSE** from `POST /agent/turn`. The agent's event
  protocol already exists: `agent.run_turn(...)` is an async generator yielding
  typed dicts. The **actual** vocabulary (verified against the code, which
  differs from the module's stale docstring) is: `think_open`, `think_close`,
  `answer_open`, `delta` (scope `answer`|`think` — this is how the final answer
  streams; there is **no** single `final` event), `answer_to_think`, `tool`,
  `tool_result`, `tool_error`, `table`, `sources`, `error`. Each becomes one SSE
  `data:` line (JSON). The frontend's existing transcript consumer changes only
  its **source** (an SSE reader instead of a direct generator) — the rendering
  logic is untouched. Phase 3 freezes this as the formal wire contract.
- **Everything else** is plain REST/JSON (projects, conversations, KB, schema
  search, settings, connectors, MCP, plugins, skills).
- The frontend **never** touches `chroma_db/`, `projects/`, or the DB directly.

### 3.2 Auth across the boundary
- Reuse the existing HMAC token crypto (`auth.py` → `ocd_core/auth.py`).
- `POST /auth/login {username,password}` → signed token (constant-time compare).
- Frontend stores the token in Reflex `AuthState`; `api_client` sends it as
  `Authorization: Bearer <token>` on every call; a FastAPI dependency verifies.
- Auth **disabled (open)** when `APP_USERNAME`/`APP_PASSWORD` are unset — preserves
  current behavior. Secret env renamed `CHAINLIT_AUTH_SECRET` → `APP_AUTH_SECRET`
  (with back-compat fallback read).
- Optional `INTERNAL_API_KEY` for non-browser/service callers.

## 4. Target directory layout

```
open-claude-desktop/
├─ backend/
│  ├─ ocd_core/                    # framework-agnostic domain (single source of truth)
│  │  ├─ __init__.py
│  │  ├─ config.py                 # pydantic-settings: ALL env/constants, one place
│  │  ├─ sql_guard.py              # ✓ already extracted
│  │  ├─ bigquery.py               # client (thread-safe), dry-run, execute_sql, cost
│  │  ├─ schema_catalog.py         # build/version/search catalog (Chroma)
│  │  ├─ llm.py                    # GLM/Zhipu client + streaming
│  │  ├─ agent.py                  # run_turn ReAct loop (yields typed events)
│  │  ├─ projects.py               # project CRUD (DB-backed)
│  │  ├─ conversations.py          # conversation CRUD (DB-backed)
│  │  ├─ knowledge.py              # KB ingest/search, wiki, file extraction
│  │  ├─ observability.py          # _observe, rotating audit log, rate limiter
│  │  ├─ auth.py                   # token crypto (HMAC)
│  │  ├─ db/                       # SQLModel models + engine/session + Alembic
│  │  │  ├─ models.py  session.py
│  │  │  └─ migrations/            # alembic
│  │  └─ integrations/
│  │     ├─ mcp_registry.py        # single-spawn registry (unchanged)
│  │     ├─ connectors.py  plugins.py  web.py
│  ├─ app/                         # FastAPI HTTP surface over ocd_core
│  │  ├─ main.py                   # app, routers, auth middleware, lifespan
│  │  ├─ deps.py  schemas.py
│  │  └─ routes/
│  │     ├─ agent.py               # POST /agent/turn  (SSE)
│  │     ├─ projects.py  conversations.py  knowledge.py
│  │     ├─ schema.py  integrations.py  settings.py  auth.py  health.py
│  ├─ content/                     # backend-owned, committed
│  │  ├─ knowledge/                # RAG markdown (was knowledge/)
│  │  ├─ skills/                   # runtime agent skills (was skills/)  ← not .claude/skills
│  │  └─ plugins/                  # runtime agent tools (was plugins/)
│  ├─ mcp_servers/                 # bundled demo server(s) (was mcp_servers/)
│  ├─ tests/
│  ├─ Dockerfile
│  └─ pyproject.toml               # fastapi, uvicorn, sse-starlette, sqlmodel, alembic,
│                                  #   psycopg, zhipuai, google-cloud-bigquery, chromadb, mcp
├─ frontend/
│  ├─ aj360_app/                   # single nesting (kills aj360_app/aj360_app/aj360_app.py)
│  │  ├─ __init__.py
│  │  ├─ app.py                    # pages/routing/layout (was aj360_app.py)
│  │  ├─ state.py                  # AppState → calls backend via api_client
│  │  ├─ api_client.py             # NEW: typed HTTP + SSE client to backend
│  │  ├─ auth.py                   # Reflex AuthState + login_page
│  │  └─ components/               # the 1,417-line UI, split by concern
│  ├─ assets/theme.css
│  ├─ rxconfig.py
│  ├─ tests/
│  ├─ Dockerfile
│  └─ pyproject.toml               # reflex, httpx, httpx-sse
├─ runtime/                        # data, GITIGNORED, owned by backend
│  └─ chroma_db/  logs/  .files/   (projects/conversations now in Postgres)
├─ .claude/
│  ├─ settings.json                # permissions + hooks
│  ├─ rules/                       # path-scoped: backend-api, frontend, testing
│  ├─ agents/                      # e.g. code-reviewer
│  └─ commands/                    # e.g. /run-backend, /run-frontend, /migrate
├─ CLAUDE.md
├─ docs/                           # architecture-audit.md, specs/, aj360.md schema docs
├─ docker-compose.yml              # postgres + backend + frontend
├─ .github/workflows/ci.yml        # matrix per service: ruff, mypy, pytest, gitleaks
├─ .gitignore  .editorconfig  .pre-commit-config.yaml
├─ README.md  CONTRIBUTING.md  SECURITY.md
```

## 5. Current → target file mapping

| Current | Target | Action |
|---|---|---|
| `app.py` (Chainlit, ~2,437 ln) | — | **Retire**; salvage unique logic into `ocd_core` first (see §6) |
| `run.py`, `.chainlit/`, `chainlit.md`, root `config.toml` | — | **Delete** (Chainlit shell) |
| `schema.sql` (Chainlit PG DDL) | — | **Delete**; replaced by SQLModel + Alembic |
| `aj360_app/aj360_app/core.py` | `backend/ocd_core/{config,bigquery,schema_catalog,llm,projects,conversations,knowledge}.py` | **Split** |
| `aj360_app/aj360_app/agent.py` | `backend/ocd_core/agent.py` | **Move** |
| `aj360_app/aj360_app/integrations.py` | `backend/ocd_core/integrations/*` | **Split** |
| `aj360_app/aj360_app/mcp_registry.py` | `backend/ocd_core/integrations/mcp_registry.py` | **Move** |
| `aj360_app/aj360_app/auth.py` | crypto → `backend/ocd_core/auth.py`; Reflex parts → `frontend/aj360_app/auth.py` | **Split** |
| `aj360_app/aj360_app/state.py` | `frontend/aj360_app/state.py` | **Move + rewire to `api_client`** |
| `aj360_app/aj360_app/aj360_app.py` | `frontend/aj360_app/app.py` + `components/` | **Move + split UI** |
| `aj360_app/rxconfig.py`, `assets/` | `frontend/` | **Move** |
| `ocd_core/sql_guard.py` | `backend/ocd_core/sql_guard.py` | **Move** |
| `skills/`, `plugins/`, `knowledge/` | `backend/content/{skills,plugins,knowledge}/` | **Move** (resolves `skills/` vs `.claude/skills` collision) |
| `mcp_servers/`, `mcp_servers.json`, `connectors.json`, `settings.json` | `backend/` | **Move** (backend config/content) |
| `chroma_db/`, `logs/`, `.files/` | `runtime/` | **Move** (gitignored) |
| `projects/` (JSON registry + conversations) | Postgres | **Migrate** (one-time script), then archive |
| `kuzu_db`, `kuzu_db.wal` | — | **Delete** (dead — referenced nowhere in code) |
| `Dockerfile` (Chainlit) | `backend/Dockerfile` + `frontend/Dockerfile` | **Replace** |
| `pyproject.toml` (root) | `backend/pyproject.toml` + `frontend/pyproject.toml` | **Split** |
| `tests/` (5 files, `spec_from_file_location`) | `backend/tests/` + `frontend/tests/`, real imports | **Split + convert** (audit #5) |
| `aj360.md`, `aj360-ux-curation*.md` | `docs/` | **Move** |

## 6. Logic salvaged from `app.py` before deletion

The mapping found domain behavior that exists **only** in Chainlit's `app.py` and
is not yet in the Reflex/core path. These must be ported into `ocd_core` (with
tests) before `app.py` is deleted:

1. **Per-user rate limiting** (sliding window) → `ocd_core/observability.py`.
2. **Per-project table-allowlist enforcement** inside `run_sql` (substring match
   against the project allowlist) → enforced in `ocd_core/bigquery.py` /
   `agent.py`. (Reflex has `get_project_allowlist()` but never calls it.)
3. **Rotating audit log** (`logs/agent_audit.jsonl`, `RotatingFileHandler`) →
   `ocd_core/observability.py`. (Audit #17; do not log secrets/usernames.)
4. **Eager schema-catalog rebuild on startup** (version-hash check) →
   `ocd_core/schema_catalog.py`, called from FastAPI lifespan startup.
5. **Slash-command parsing + skills auto-trigger execution** (today split across
   Chainlit's `on_message` handler and Reflex `integrations.matching_skill`) →
   consolidated into the **UI-agnostic core agent path** (`ocd_core/agent.py`,
   helped by an `ocd_core/commands.py` parser + the existing skill matcher).
   **Directive (approved):** command parsing, regex triggers, and skill
   auto-triggering must live in `ocd_core`, never in a UI shell — so the CLI,
   the Reflex frontend, and any external API client all get identical command
   and skill behavior without re-implementing the parser.

Chainlit-only infra with no Reflex need is **dropped**: the SQLAlchemy data-layer
+ GCS file persistence, Postgres chat threads (`schema.sql`), and the
Chainlit-specific config/i18n.

## 7. Data model & migration

### Models (SQLModel)
- **Project**: `id`, `slug`, `name`, `instructions`, `allowlist` (JSON),
  `created_at`, `updated_at`.
- **Conversation**: `id`, `project_id` (FK), `title`, `pinned` (bool),
  `transcript` (JSONB — the typed message list, for parity with today's JSON),
  `created_at`, `updated_at`.
- **Setting**: key/value for app settings (model, effort, theme) — or a single
  row; `GET/PUT /settings`.

> Storing `transcript` as JSONB preserves the current rich event shape
> (user/final/thinking/tool/sources/table/error) with no lossy normalization.
> A normalized `Message` table is a deliberate later option, not part of this work.

### Migration
- One-time, **idempotent** script: read `runtime`/legacy `projects/_registry.json`
  + each `projects/<id>/conversations/*.json`, upsert into Postgres by id.
- Take a backup of the JSON tree first; verify row counts vs file counts; keep
  the JSON as read-only archive until the user confirms parity.
- Alembic owns the schema; `alembic upgrade head` runs on backend startup
  (or via a `/migrate` command) for dev.

## 8. Backend API surface (initial)

```
Auth:          POST /auth/login
Agent:         POST /agent/turn                         (SSE: typed agent events)
Projects:      GET/POST /projects · GET/PATCH/DELETE /projects/{id}
               GET/PUT /projects/{id}/instructions · /projects/{id}/allowlist
Conversations: GET /projects/{id}/conversations · POST .../conversations
               GET/PATCH/DELETE /conversations/{cid} · POST /conversations/{cid}/move
Knowledge:     POST /projects/{id}/files · GET /projects/{id}/files
               GET /projects/{id}/capacity · DELETE /projects/{id}/files/{fid}
Schema:        GET /schema/search · POST /schema/rebuild · GET /schema/status
Integrations:  GET/POST/DELETE /connectors · POST /connectors/{id}/test
               GET/POST/DELETE /mcp-servers · GET /mcp-servers/{id}/tools
               GET /plugins · GET /skills
Settings:      GET/PUT /settings
Health:        GET /healthz
```

## 9. The `.claude/` layer (initial set)

- **`CLAUDE.md`**: the two-service layout; how to run each service; test/lint/
  type commands; the **invariant** that `ocd_core` must never import Reflex or
  FastAPI; "domain logic goes in `ocd_core`, transport in `app/`, UI in
  `frontend/`."
- **`.claude/settings.json`**: `permissions.allow` for the common commands
  (`pytest`, `ruff`, `uvicorn`, `reflex run`, `alembic`, `docker compose`); a
  PostToolUse `ruff --fix` hook on edit/write of `*.py`.
- **`.claude/rules/`**: `backend-api.md` (paths `backend/app/routes/**`),
  `frontend.md` (paths `frontend/**`), `testing.md` (paths `**/tests/**`,
  `**/test_*.py`).
- **`.claude/agents/code-reviewer.md`**, **`.claude/commands/`**:
  `/run-backend`, `/run-frontend`, `/migrate`.

> The app's runtime `content/skills/` and `content/plugins/` are **not** Claude
> Code skills and are left untouched by this layer.

## 10. Migration phases (each leaves a working app + green tests)

This continues the audit's incremental, TDD-sliced approach. No big-bang.

1. **Consolidate the core (in-process).** Create `backend/ocd_core/`; move
   Reflex's domain modules in; add `config.py`; salvage `app.py`'s unique logic
   (§6). Reflex imports `ocd_core` directly. **Duplication eliminated** — biggest
   win, lowest risk. *Verify:* Reflex app runs unchanged; ocd_core unit tests
   (real imports) green.
2. **Persistence slice.** Add SQLModel models, Alembic, the JSON→Postgres
   migration; `projects.py`/`conversations.py` become DB-backed. *Verify:*
   migrated data round-trips; CRUD tests green; Reflex still works.
3. **Wrap in FastAPI.** Add `backend/app/` (REST + the SSE agent route) over the
   same `ocd_core`. *Verify:* backend runs standalone; route tests (TestClient,
   mocked BigQuery/GLM) green; an SSE turn streams end-to-end.
4. **Thin the frontend.** Add `api_client.py`; swap `state.py`'s direct core
   calls for HTTP/SSE; split the UI into `components/`. *Verify:* two services up
   via compose; full chat + projects flow works against the backend.
5. **Retire Chainlit.** Delete `app.py`, `.chainlit/`, `chainlit.md`,
   `schema.sql`, Chainlit Postgres/GCS; drop the `chainlit` extra. *Verify:* no
   references remain; app fully functional on the new path.
6. **Finalize layout + ops + `.claude/`.** `runtime/` move, `backend/content/`,
   convert remaining tests to real imports (#5), `kuzu_db` delete; two
   Dockerfiles + compose; CI matrix per service; `CLAUDE.md` + `.claude/`.
   *Verify:* `docker compose up` brings up postgres + backend + frontend; CI
   green on both services.

## 11. Testing strategy

- **`ocd_core`**: pure unit tests via **real imports** (closes audit #5) — SQL
  guard, config, projects/conversations CRUD, agent event-stream parsing, rate
  limiter, allowlist enforcement.
- **Backend `app`**: FastAPI `TestClient`; BigQuery/GLM mocked; one real SSE
  streaming test against a fake agent generator.
- **Migration**: fixture JSON tree → assert DB rows + transcript parity.
- **Frontend**: `api_client` against a mocked backend (httpx transport);
  transcript/state reducer logic.
- **CI**: per-service matrix on Python 3.12 — `ruff check` (promoted to
  **blocking**), `mypy`, `pytest`, `gitleaks`.

## 12. Risks & mitigations

| Risk | Mitigation |
|---|---|
| SSE streaming (disconnects, partial events, backpressure) | Keep `run_turn` unchanged — only transport changes; reconnection-tolerant client; explicit done/error events |
| Data loss in JSON→Postgres migration | Idempotent upsert, pre-backup, count + transcript verification, JSON kept as archive until confirmed |
| Dropping an `app.py`-only feature | §6 enumerates them explicitly; each ported with a test before deletion |
| Reflex event handler doing network I/O | Reflex handlers are async; `httpx` async client + `httpx-sse`; current code already consumes an async generator — pattern preserved |
| Windows dev ergonomics (two services) | `docker compose up` for one-command local; documented two-terminal flow (`uvicorn` + `reflex run`, `REFLEX_USE_NPM=true`) |
| Secret handling regression | `gitleaks` stays (pre-commit + CI); no secrets in logs; **outstanding: rotate the previously-leaked SA key + `.env`/GLM secrets** |

## 13. Open questions

None blocking. Deferred-by-design: normalized message table; swapping ChromaDB
for pgvector; independent release cadence for the two services.
