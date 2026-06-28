# Phase 3 — FastAPI Service + SSE Agent Stream — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a FastAPI service (`backend/app/`) over the existing `ocd_core` — a streaming `POST /agent/turn` (SSE) plus the complete REST surface the Reflex frontend uses — with per-user rate-limit/audit and a hardened parsed-`referenced_tables` allowlist.

**Architecture:** Additive only — `ocd_core` + the Reflex app are unchanged except a small auth-crypto extraction and the allowlist hardening. REST routes are sync `def` (FastAPI threadpools them, calling sync `ocd_core`); the agent route is `async` and iterates the async `run_turn` generator, streaming each event as SSE via `sse-starlette`. Auth is an optional Bearer dependency (disabled when creds are unset).

**Tech Stack:** Python 3.12 · FastAPI · uvicorn · sse-starlette · Pydantic · httpx (TestClient) · python-multipart · pytest · SQLite (tests) behind SQLModel.

---

## Scope & contract (read first)

- **Spec:** `docs/superpowers/specs/2026-06-28-phase3-fastapi-sse-design.md`.
- **Environment:** repo `D:\HP\Projects\open-claude-desktop`, branch `refactor/phase3-fastapi`. Interpreter `venv312\Scripts\python.exe`. Tests from **repo root**. `ocd_core` editable-installed. Commit messages end with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **No external calls in tests:** mock BigQuery (`execute_sql`/dry-run), GLM (`run_turn`), and ChromaDB. The `db` SQLite fixture (in `backend/tests/conftest.py`) isolates DB + filesystem; request it where routes touch the DB.
- **The agent route resolves the skill** from the goal (UI-agnostic, per the §6 directive) — it does NOT handle the fixed slash-commands (`/projects` etc.); those are UI/REST actions.

## File structure

**Created:**
- `backend/ocd_core/auth.py` — extracted HMAC crypto
- `backend/app/__init__.py`, `main.py`, `deps.py`, `schemas.py`, `sse.py`
- `backend/app/routes/__init__.py`, `health.py`, `auth.py`, `agent.py`, `projects.py`, `conversations.py`, `settings.py`, `knowledge.py`, `schema.py`, `integrations.py`
- `backend/tests/` — `test_ocd_auth.py`, `test_app_health_auth.py`, `test_allowlist_parsed.py`, `test_agent_sse.py`, `test_rest_projects.py`, `test_rest_conversations.py`, `test_rest_settings.py`, `test_rest_knowledge_schema_integrations.py`

**Modified:**
- `aj360_app/aj360_app/auth.py` — repoint crypto import to `ocd_core.auth`
- `backend/ocd_core/bigquery.py` (`_dry_run`, `execute_sql`), `backend/ocd_core/sql_guard.py` (`tables_off_allowlist`), `backend/tests/test_allowlist.py`
- `backend/pyproject.toml` — add fastapi/uvicorn/sse-starlette/httpx/python-multipart

---

## Task 1: extract `ocd_core/auth.py` (HMAC crypto)

The Reflex `aj360_app/aj360_app/auth.py` holds the token crypto coupled with Reflex `AuthState`/`login_page`. Extract the **pure crypto** so the backend can verify tokens without importing the frontend.

**Files:**
- Create: `backend/ocd_core/auth.py`
- Modify: `aj360_app/aj360_app/auth.py` (import the crypto from ocd_core)
- Create: `backend/tests/test_ocd_auth.py`

- [ ] **Step 1: Read the source.** Open `aj360_app/aj360_app/auth.py` and identify the three pure-crypto functions (`make_token`, `verify_token`, `credentials_ok`) + the module constants they use (`APP_USERNAME`, `APP_PASSWORD`, the auth secret env — `CHAINLIT_AUTH_SECRET`, `AUTH_SESSION_TTL_SEC`). Note their exact signatures.

- [ ] **Step 2: Write the failing test** (`backend/tests/test_ocd_auth.py`)

```python
import importlib

def test_token_roundtrip_and_tamper(monkeypatch):
    monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "test-secret")
    a = importlib.reload(importlib.import_module("ocd_core.auth"))
    tok = a.make_token("alice")
    assert a.verify_token(tok) == "alice"            # valid → username
    assert a.verify_token(tok + "x") is None         # tampered → None
    assert a.verify_token("not.a.token") is None

def test_credentials_ok(monkeypatch):
    monkeypatch.setenv("APP_USERNAME", "u")
    monkeypatch.setenv("APP_PASSWORD", "p")
    a = importlib.reload(importlib.import_module("ocd_core.auth"))
    assert a.credentials_ok("u", "p") is True
    assert a.credentials_ok("u", "wrong") is False

def test_auth_disabled_when_unset(monkeypatch):
    monkeypatch.delenv("APP_USERNAME", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    a = importlib.reload(importlib.import_module("ocd_core.auth"))
    assert a.auth_enabled() is False
```

- [ ] **Step 3: Run — expect FAIL** (`ModuleNotFoundError: No module named 'ocd_core.auth'`). `venv312/Scripts/python.exe -m pytest backend/tests/test_ocd_auth.py -v`

- [ ] **Step 4: Create `backend/ocd_core/auth.py`.** MOVE the three crypto functions VERBATIM from `aj360_app/aj360_app/auth.py` (adjust only import refs — they should need none beyond stdlib `hmac`/`hashlib`/`base64`/`time`/`os`). Add a tiny helper:
```python
def auth_enabled() -> bool:
    """Auth is enforced only when BOTH username and password are configured."""
    return bool(os.getenv("APP_USERNAME") and os.getenv("APP_PASSWORD"))
```
Read the auth secret with back-compat: prefer `APP_AUTH_SECRET`, fall back to `CHAINLIT_AUTH_SECRET`. If the original `make_token`/`verify_token` assertions in the test (return username / None on tamper) don't match the real signatures, **match the real behavior** and adjust the test, noting it.

- [ ] **Step 5: Repoint the Reflex auth module.** In `aj360_app/aj360_app/auth.py`, delete the three moved crypto defs and `from ocd_core.auth import make_token, verify_token, credentials_ok  # noqa: F401`. Keep `AuthState`/`login_page`. Verify: `venv312/Scripts/python.exe -c "import sys; sys.path.insert(0,'aj360_app'); import aj360_app.aj360_app as ui; print('reflex ui import OK')"`.

- [ ] **Step 6: Run — expect PASS** + full suite green. `venv312/Scripts/python.exe -m pytest backend/tests -q` (prior 81 + 3 new).

- [ ] **Step 7: Commit**
```bash
git add -A
git commit -m "refactor(auth): extract HMAC crypto into ocd_core.auth (backend-usable)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: app skeleton + health + optional-auth + login

**Files:**
- Modify: `backend/pyproject.toml` (deps)
- Create: `backend/app/__init__.py` (empty), `backend/app/main.py`, `backend/app/deps.py`, `backend/app/schemas.py`, `backend/app/routes/__init__.py` (empty), `backend/app/routes/health.py`, `backend/app/routes/auth.py`
- Create: `backend/tests/test_app_health_auth.py`

- [ ] **Step 1: Install + declare deps.** `venv312/Scripts/python.exe -m pip install fastapi uvicorn sse-starlette httpx python-multipart`. Add `"fastapi"`, `"uvicorn"`, `"sse-starlette"`, `"httpx"`, `"python-multipart"` to `backend/pyproject.toml` `[project] dependencies`; `pip install -e ./backend --no-deps`. Add `"app"` and `"app.routes"` to `[tool.setuptools] packages` (alongside `ocd_core`, `ocd_core.db`).

- [ ] **Step 2: Write the failing test** (`backend/tests/test_app_health_auth.py`)

```python
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from backend.app.main import app
    return TestClient(app)


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_auth_disabled_allows_unauthed(client, monkeypatch):
    monkeypatch.delenv("APP_USERNAME", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    # a protected route is open when auth is disabled
    r = client.get("/settings")
    assert r.status_code == 200


def test_login_and_protected_route(monkeypatch):
    monkeypatch.setenv("APP_USERNAME", "u")
    monkeypatch.setenv("APP_PASSWORD", "p")
    monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "s")
    from backend.app.main import app
    c = TestClient(app)
    assert c.get("/settings").status_code == 401          # no token
    tok = c.post("/auth/login", json={"username": "u", "password": "p"}).json()["token"]
    r = c.get("/settings", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert c.post("/auth/login", json={"username": "u", "password": "x"}).status_code == 401
```
NOTE: `/settings` is implemented in Task 5; for THIS task, add a temporary protected probe route `GET /settings` in `routes/health.py` that just returns `ocd_core` settings (it will be replaced in Task 5). OR gate the test's `/settings` calls behind Task 5. To keep Task 2 self-contained, implement a minimal `GET /settings` here returning `settings.get_settings()` under the auth dependency, and Task 5 will move it to `routes/settings.py`.

- [ ] **Step 3: Run — expect FAIL** (`ModuleNotFoundError: No module named 'backend.app'` or import error). `venv312/Scripts/python.exe -m pytest backend/tests/test_app_health_auth.py -v`

- [ ] **Step 4: `backend/app/schemas.py`** (base models used across tasks)
```python
from __future__ import annotations
from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    token: str


class Message(BaseModel):
    role: str
    content: str
    kind: str = "user"
```

- [ ] **Step 5: `backend/app/deps.py`** (optional-auth current-user dependency)
```python
from __future__ import annotations
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from ocd_core import auth

_bearer = HTTPBearer(auto_error=False)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    """Optional auth: when disabled (no creds configured) → 'anonymous'.
    When enabled → require a valid Bearer token, else 401."""
    if not auth.auth_enabled():
        return "anonymous"
    user = auth.verify_token(creds.credentials) if creds else None
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing token")
    return user
```

- [ ] **Step 6: `backend/app/routes/health.py`**
```python
from __future__ import annotations
from fastapi import APIRouter, Depends
from ocd_core import settings
from ..deps import current_user

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
def readyz() -> dict:
    from ocd_core.db.engine import get_engine
    try:
        get_engine().connect().close()
        return {"status": "ready"}
    except Exception as e:
        return {"status": "unavailable", "error": str(e)}


# Temporary settings probe (moved to routes/settings.py in Task 5)
@router.get("/settings")
def get_settings(user: str = Depends(current_user)) -> dict:
    return settings.get_settings()
```

- [ ] **Step 7: `backend/app/routes/auth.py`**
```python
from __future__ import annotations
from fastapi import APIRouter, HTTPException, status
from ocd_core import auth
from ..schemas import LoginRequest, TokenResponse

router = APIRouter(prefix="/auth")


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest) -> TokenResponse:
    if not auth.credentials_ok(body.username, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad credentials")
    return TokenResponse(token=auth.make_token(body.username))
```

- [ ] **Step 8: `backend/app/main.py`**
```python
from __future__ import annotations
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import health, auth

app = FastAPI(title="ocd backend", version="0.4.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(health.router)
app.include_router(auth.router)
```
(Routers for agent/projects/conversations/settings/knowledge/schema/integrations are added in later tasks.)

- [ ] **Step 9: Run — expect PASS** + full suite. `venv312/Scripts/python.exe -m pytest backend/tests -q`. Also smoke the server import: `venv312/Scripts/python.exe -c "from backend.app.main import app; print('app OK', len(app.routes), 'routes')"`.

- [ ] **Step 10: Commit**
```bash
git add -A
git commit -m "feat(app): FastAPI skeleton — health, readyz, optional-auth, login" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: harden the allowlist (parsed `referenced_tables`)

Replace the substring allowlist with a parsed check using the dry-run's `referenced_tables`, so a commented/string table name can't bypass it.

**Files:**
- Modify: `backend/ocd_core/sql_guard.py` (`tables_off_allowlist`)
- Modify: `backend/ocd_core/bigquery.py` (`_dry_run`, `execute_sql`)
- Modify: `backend/tests/test_allowlist.py` (update to the new signature)
- Create: `backend/tests/test_allowlist_parsed.py`

- [ ] **Step 1: Write the failing tests** (`backend/tests/test_allowlist_parsed.py`)

```python
from ocd_core import sql_guard


def test_parsed_allowlist_blocks_off_list_table():
    # allowlist permits aj360.events; referencing aj360.users is blocked
    assert sql_guard.tables_off_allowlist(["aj360.events"], ["aj360.events"]) is False
    assert sql_guard.tables_off_allowlist(["aj360.users"], ["aj360.events"]) is True
    # any off-list reference blocks, even alongside an allowed one
    assert sql_guard.tables_off_allowlist(["aj360.events", "aj360.users"], ["aj360.events"]) is True


def test_empty_allowlist_allows_all():
    assert sql_guard.tables_off_allowlist(["anything.here"], []) is False


def test_comment_injection_no_longer_bypasses():
    # the SQL `SELECT * FROM aj360.users -- aj360.events` resolves referenced_tables
    # to [aj360.users] (the comment is NOT a reference) -> blocked.
    assert sql_guard.tables_off_allowlist(["aj360.users"], ["aj360.events"]) is True
```

- [ ] **Step 2: Run — expect FAIL** (current `tables_off_allowlist(sql, allowlist)` takes a SQL string, not a list → wrong results). `venv312/Scripts/python.exe -m pytest backend/tests/test_allowlist_parsed.py -v`

- [ ] **Step 3: Rewrite `sql_guard.tables_off_allowlist`** to the parsed-reference signature:
```python
def tables_off_allowlist(referenced_tables: list[str], allowlist: list[str]) -> bool:
    """True if a non-empty allowlist is in force and ANY referenced table is not
    in it. `referenced_tables` are qualified ids (e.g. "dataset.table") parsed from
    the BigQuery dry-run — not substrings — so commented/quoted names can't bypass.
    Empty allowlist => no restriction (all allowed)."""
    if not allowlist:
        return False
    allowed = {a.lower() for a in allowlist}
    refs = [t.lower() for t in (referenced_tables or [])]
    if not refs:
        return True  # allowlist in force but we couldn't resolve refs -> deny (fail-safe)
    return any(r not in allowed for r in refs)
```

- [ ] **Step 4: Update `_dry_run` to return `referenced_tables`** (`backend/ocd_core/bigquery.py`). Change its return to a 5-tuple and read the job's referenced tables:
```python
def _dry_run(sql: str):
    from google.cloud.bigquery import QueryJobConfig
    client = get_bq_client()
    try:
        job = client.query(sql, QueryJobConfig(dry_run=True, use_query_cache=False))
        stmt = getattr(job, "statement_type", None) or "UNKNOWN"
        refs = [f"{t.dataset_id}.{t.table_id}" for t in (job.referenced_tables or [])]
        return True, stmt, job.total_bytes_processed or 0, refs, None
    except Exception as e:
        return False, None, 0, [], str(e)
```

- [ ] **Step 5: Reorder `execute_sql`** to check the allowlist AFTER the dry-run, using the parsed refs. Replace the early substring block (the `if active_project:` block before the dry-run) with: dry-run first, then:
```python
    ok, stmt, est_bytes, refs, err = _dry_run(sql)
    if not ok:
        return {"ok": False, "stmt": stmt, "error": err,
                "agent_text": f"VALIDATION FAILED (0 rows scanned). Fix and retry.\nError: {err}"}

    if active_project:
        from .projects import get_project_allowlist
        from .sql_guard import tables_off_allowlist
        allow = get_project_allowlist(active_project)
        if tables_off_allowlist(refs, allow):
            return {"ok": False, "error": "allowlist",
                    "agent_text": f"SQL REJECTED: project allows only: {', '.join(allow)}"}
```
Keep the rest (banned-alias check can stay before the dry-run; the mutation/cost checks stay after). Ensure the function still returns the same result dict shape.

- [ ] **Step 6: Update the OLD `backend/tests/test_allowlist.py`.** Its tests call `tables_off_allowlist(sql_string, allowlist)`. Rewrite those assertions to the parsed signature (lists), or DELETE the file if `test_allowlist_parsed.py` fully supersedes it (it does — they tested the substring behavior we deliberately replaced). Prefer deleting `test_allowlist.py` and keeping `test_allowlist_parsed.py` (note it in the commit, per the storage-rewrite precedent).

- [ ] **Step 7: Add an `execute_sql` guard test** (append to `test_allowlist_parsed.py`) using a fake dry-run so no BigQuery is hit:
```python
def test_execute_sql_blocks_off_allowlist(monkeypatch, db, tmp_path):
    from ocd_core import bigquery, projects
    projects.create_project("Scoped")
    # allowlist the project to aj360.events only
    from ocd_core.db.engine import session
    from ocd_core.db.models import Project
    with session() as s:
        p = s.get(Project, "scoped"); p.allowlist = ["aj360.events"]; s.add(p)
    monkeypatch.setattr(bigquery, "_dry_run",
                        lambda sql: (True, "SELECT", 10, ["aj360.users"], None))
    out = bigquery.execute_sql("SELECT * FROM aj360.users", active_project="scoped")
    assert out["ok"] is False and out["error"] == "allowlist"
```

- [ ] **Step 8: Run — expect PASS** + full suite. `venv312/Scripts/python.exe -m pytest backend/tests -q`.

- [ ] **Step 9: Commit**
```bash
git add -A
git commit -m "feat(sql_guard): harden allowlist to parsed referenced_tables (no comment bypass)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: the agent SSE endpoint (centerpiece)

**Files:**
- Create: `backend/app/sse.py`, `backend/app/routes/agent.py`
- Modify: `backend/app/schemas.py` (agent request), `backend/app/main.py` (include router)
- Create: `backend/tests/test_agent_sse.py`

- [ ] **Step 1: Write the failing test — the SSE MOCKING STRATEGY** (`backend/tests/test_agent_sse.py`)

The strategy: **monkeypatch `ocd_core.agent.run_turn` with a fake async generator** that yields a scripted event sequence; assert the endpoint streams matching SSE frames. No GLM/BigQuery is touched.

```python
import json
import pytest
from fastapi.testclient import TestClient


async def _fake_run_turn(*args, **kwargs):
    # mirrors the real event vocabulary
    yield {"type": "think_open", "phase": "plan"}
    yield {"type": "delta", "scope": "think", "text": "planning…"}
    yield {"type": "think_close", "elapsed": 0.1}
    yield {"type": "answer_open"}
    yield {"type": "delta", "scope": "answer", "text": "Hello"}
    yield {"type": "tool", "id": "t1", "name": "run_sql", "input": "SELECT 1"}
    yield {"type": "table", "id": "t1", "columns": ["n"], "rows": [{"n": 1}], "total": 1, "bytes": 10}


@pytest.fixture
def client(monkeypatch):
    from ocd_core import agent
    monkeypatch.setattr(agent, "run_turn", _fake_run_turn)
    from backend.app.main import app
    return TestClient(app)


def _read_sse(resp):
    """Parse an SSE response body into [(event, data_dict), ...]."""
    events = []
    cur = {}
    for line in resp.text.splitlines():
        if line.startswith("event:"):
            cur["event"] = line[6:].strip()
        elif line.startswith("data:"):
            cur["data"] = json.loads(line[5:].strip())
        elif line == "" and cur:
            events.append(cur); cur = {}
    return events


def test_agent_turn_streams_events(client, db):
    body = {"project_id": None, "goal": "hi", "history": [], "model": "glm-4-plus",
            "effort": "Low", "options": {}, "enabled_plugins": [],
            "enabled_connectors": [], "enabled_mcp": []}
    r = client.post("/agent/turn", json=body)
    assert r.status_code == 200
    evs = _read_sse(r)
    types = [e["event"] for e in evs]
    assert types[:4] == ["think_open", "delta", "think_close", "answer_open"]
    assert "table" in types and types[-1] == "done"   # terminal frame
    # the data payloads round-trip the event dicts
    delta = next(e for e in evs if e["event"] == "delta")
    assert delta["data"]["text"] in ("planning…", "Hello")


def test_agent_turn_rate_limited(monkeypatch, db):
    from ocd_core import agent, observability
    monkeypatch.setattr(agent, "run_turn", _fake_run_turn)
    monkeypatch.setattr(observability, "check_rate_limit", lambda user: False)  # always block
    from backend.app.main import app
    c = TestClient(app)
    r = c.post("/agent/turn", json={"project_id": None, "goal": "hi", "history": [],
                                    "model": "m", "effort": "Low", "options": {},
                                    "enabled_plugins": [], "enabled_connectors": [], "enabled_mcp": []})
    assert r.status_code == 429
```

- [ ] **Step 2: Run — expect FAIL** (`/agent/turn` not found → 404). `venv312/Scripts/python.exe -m pytest backend/tests/test_agent_sse.py -v`

- [ ] **Step 3: `backend/app/sse.py`**
```python
from __future__ import annotations
import json
from sse_starlette.sse import ServerSentEvent


def format_event(ev: dict) -> ServerSentEvent:
    """One run_turn event dict -> an SSE frame (event: <type>, data: <json>)."""
    return ServerSentEvent(event=ev.get("type", "message"), data=json.dumps(ev, default=str))
```

- [ ] **Step 4: Add the agent request schema** (`backend/app/schemas.py`)
```python
class AgentOptions(BaseModel):
    web_search: bool = False
    research: bool = False
    web_fetch: bool = False
    code_exec: bool = False
    bash: bool = False
    text_editor: bool = False
    memory: bool = False


class AgentTurnRequest(BaseModel):
    project_id: str | None = None
    goal: str
    history: list[Message] = []
    model: str
    effort: str = "High"
    options: AgentOptions = AgentOptions()
    enabled_plugins: list[str] = []
    enabled_connectors: list[str] = []
    enabled_mcp: list[str] = []
```

- [ ] **Step 5: `backend/app/routes/agent.py`**
```python
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status
from sse_starlette.sse import EventSourceResponse
from ocd_core import agent, integrations, projects, observability, commands, skills
from ..deps import current_user
from ..schemas import AgentTurnRequest
from ..sse import format_event

router = APIRouter()


@router.post("/agent/turn")
async def agent_turn(req: AgentTurnRequest, user: str = Depends(current_user)):
    # 1. per-user rate limit (the genuine new guard)
    if not observability.check_rate_limit(user):
        observability.audit({"event": "rate_limited", "user": user, "goal": req.goal[:200]})
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate limit exceeded")

    # 2. resolve skill (UI-agnostic) + project instructions + tools
    goal, skill_name, _ = commands.resolve_skill(req.goal)
    skill_instr = (skills.get_skill(skill_name) or {}).get("instructions", "") if skill_name else ""
    proj_instr = projects.get_project_instructions(req.project_id) if req.project_id else ""
    extra_tools = integrations.agent_tools(req.enabled_plugins, req.enabled_connectors, req.enabled_mcp)
    observability.audit({"event": "agent_turn", "user": user,
                         "project": req.project_id, "goal": goal[:200]})

    o = req.options
    history = [m.model_dump() for m in req.history]

    async def stream():
        try:
            async for ev in agent.run_turn(
                goal, history, req.project_id, req.model, proj_instr,
                effort=req.effort, web_search=o.web_search, skill_instructions=skill_instr,
                research=o.research, extra_tools=extra_tools, web_fetch=o.web_fetch,
                code_exec=o.code_exec, bash=o.bash, text_editor=o.text_editor, memory=o.memory):
                yield format_event(ev)
        except Exception as e:  # surface as an error event, then close
            yield format_event({"type": "error", "text": str(e)})
        yield format_event({"type": "done"})

    return EventSourceResponse(stream())
```
NOTE: confirm `agent.run_turn`'s real parameter names against `backend/ocd_core/agent.py` and match them exactly (the call above mirrors `state.py`). If `commands.resolve_skill`/`skills.get_skill` have different return shapes, adapt (resolve_skill returns `(goal, skill_name_or_'', via_auto)`; `get_skill` returns a dict with `instructions`).

- [ ] **Step 6: Register the router** in `backend/app/main.py`: `from .routes import health, auth, agent` and `app.include_router(agent.router)`.

- [ ] **Step 7: Run — expect PASS** + full suite. `venv312/Scripts/python.exe -m pytest backend/tests -q`.

- [ ] **Step 8: Commit**
```bash
git add -A
git commit -m "feat(app): POST /agent/turn SSE stream + per-user rate-limit + audit" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: REST — projects + conversations + settings

Thin sync routes over `ocd_core`. **All return the `ocd_core` dict shapes unchanged** (datetimes already ISO strings). Move the temporary `/settings` probe out of `health.py` into `routes/settings.py`.

**Files:**
- Modify: `backend/app/schemas.py` (CRUD bodies), `backend/app/main.py` (routers), `backend/app/routes/health.py` (remove temp /settings)
- Create: `backend/app/routes/projects.py`, `conversations.py`, `settings.py`
- Create: `backend/tests/test_rest_projects.py`, `test_rest_conversations.py`, `test_rest_settings.py`

- [ ] **Step 1: Add schemas** (`backend/app/schemas.py`)
```python
class ProjectCreate(BaseModel):
    name: str

class TextBody(BaseModel):       # instructions / memory
    content: str

class AllowlistBody(BaseModel):
    tables: list[str]

class ConversationCreate(BaseModel):
    first_message: str

class ConversationSave(BaseModel):
    messages: list[Message]
    title: str | None = None

class ConversationPatch(BaseModel):
    title: str | None = None
    pinned: bool | None = None

class MoveBody(BaseModel):
    dst_project_id: str

class SettingsBody(BaseModel):
    model: str | None = None
    effort: str | None = None
    theme: str | None = None
```

- [ ] **Step 2: Write failing tests** (`backend/tests/test_rest_projects.py`)
```python
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client(db):
    from backend.app.main import app
    return TestClient(app)

def test_project_crud(client):
    r = client.post("/projects", json={"name": "Alpha"})
    assert r.status_code == 200 and r.json()["id"] == "alpha"
    assert any(p["id"] == "alpha" for p in client.get("/projects").json())
    client.put("/projects/alpha/instructions", json={"content": "do X"})
    assert client.get("/projects/alpha/instructions").json()["content"] == "do X"
    client.put("/projects/alpha/allowlist", json={"tables": ["aj360.events"]})
    assert client.get("/projects/alpha/allowlist").json()["tables"] == ["aj360.events"]
    assert client.delete("/projects/alpha").status_code == 200
    assert client.get("/projects/alpha").status_code == 404
```
(`backend/tests/test_rest_conversations.py`)
```python
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client(db):
    from backend.app.main import app
    return TestClient(app)

def test_conversation_flow(client):
    client.post("/projects", json={"name": "P"})
    conv = client.post("/projects/p/conversations", json={"first_message": "hi there"}).json()
    cid = conv["id"]
    client.put(f"/projects/p/conversations/{cid}",
               json={"messages": [{"role": "user", "content": "x", "kind": "user"}], "title": "T"})
    got = client.get(f"/projects/p/conversations/{cid}").json()
    assert got["title"] == "T" and got["messages"][-1]["content"] == "x"
    client.patch(f"/projects/p/conversations/{cid}", json={"pinned": True})
    assert client.get("/projects/p/conversations").json()[0]["pinned"] is True
    assert client.post(f"/projects/p/conversations/{cid}/move", json={"dst_project_id": "general"}).json()["ok"] is True
    assert client.delete(f"/projects/general/conversations/{cid}").status_code == 200
```
(`backend/tests/test_rest_settings.py`)
```python
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client(db):
    from backend.app.main import app
    return TestClient(app)

def test_settings_get_put(client):
    base = client.get("/settings").json()
    assert "model" in base and "effort" in base
    client.put("/settings", json={"effort": "Low"})
    assert client.get("/settings").json()["effort"] == "Low"
```

- [ ] **Step 3: Run — expect FAIL** (routes 404). `venv312/Scripts/python.exe -m pytest backend/tests/test_rest_projects.py backend/tests/test_rest_conversations.py backend/tests/test_rest_settings.py -v`

- [ ] **Step 4: `backend/app/routes/projects.py`** — each handler is a thin call into `ocd_core.projects`, under `Depends(current_user)`:
```python
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from ocd_core import projects
from ..deps import current_user
from ..schemas import ProjectCreate, TextBody, AllowlistBody

router = APIRouter(prefix="/projects")

@router.get("")
def list_projects(user: str = Depends(current_user)) -> list[dict]:
    return projects.list_projects()

@router.post("")
def create_project(body: ProjectCreate, user: str = Depends(current_user)) -> dict:
    return projects.create_project(body.name)

@router.get("/{pid}")
def get_project(pid: str, user: str = Depends(current_user)) -> dict:
    p = projects.get_project(pid)
    if not p:
        raise HTTPException(404, "not found")
    return p

@router.delete("/{pid}")
def delete_project(pid: str, user: str = Depends(current_user)) -> dict:
    return {"ok": projects.delete_project(pid)}

@router.get("/{pid}/instructions")
def get_instructions(pid: str, user: str = Depends(current_user)) -> dict:
    return {"content": projects.get_project_instructions(pid)}

@router.put("/{pid}/instructions")
def put_instructions(pid: str, body: TextBody, user: str = Depends(current_user)) -> dict:
    projects.save_project_instructions(pid, body.content)
    return {"ok": True}

@router.get("/{pid}/memory")
def get_memory(pid: str, user: str = Depends(current_user)) -> dict:
    text, rel = projects.get_project_memory(pid)
    return {"content": text, "updated_rel": rel}

@router.put("/{pid}/memory")
def put_memory(pid: str, body: TextBody, user: str = Depends(current_user)) -> dict:
    projects.save_project_memory(pid, body.content)
    return {"ok": True}

@router.get("/{pid}/allowlist")
def get_allowlist(pid: str, user: str = Depends(current_user)) -> dict:
    return {"tables": projects.get_project_allowlist(pid)}

@router.put("/{pid}/allowlist")
def put_allowlist(pid: str, body: AllowlistBody, user: str = Depends(current_user)) -> dict:
    # persist on the Project row (the DB-backed module reads p.allowlist)
    from ocd_core.db.engine import session
    from ocd_core.db.models import Project
    with session() as s:
        p = s.get(Project, pid)
        if not p:
            raise HTTPException(404, "not found")
        p.allowlist = body.tables
        s.add(p)
    return {"ok": True}

@router.get("/{pid}/capacity")
def capacity(pid: str, user: str = Depends(current_user)) -> dict:
    return projects.project_capacity(pid)
```
NOTE: `projects` has no `save_project_allowlist` setter (it only has a getter), so the allowlist PUT writes the column directly via the DB (as above). If you'd rather, add `projects.save_project_allowlist(pid, tables)` to `ocd_core.projects` and call it — but keep the change minimal.

- [ ] **Step 5: `backend/app/routes/conversations.py`** — thin calls into `ocd_core.conversations`:
```python
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from ocd_core import conversations
from ..deps import current_user
from ..schemas import ConversationCreate, ConversationSave, ConversationPatch, MoveBody

router = APIRouter()

@router.get("/projects/{pid}/conversations")
def list_convs(pid: str, user: str = Depends(current_user)) -> list[dict]:
    return conversations.list_conversations(pid)

@router.post("/projects/{pid}/conversations")
def create_conv(pid: str, body: ConversationCreate, user: str = Depends(current_user)) -> dict:
    return conversations.create_conversation(pid, body.first_message)

@router.get("/projects/{pid}/conversations/{cid}")
def get_conv(pid: str, cid: str, user: str = Depends(current_user)) -> dict:
    c = conversations.get_conversation(pid, cid)
    if not c:
        raise HTTPException(404, "not found")
    return c

@router.put("/projects/{pid}/conversations/{cid}")
def save_conv(pid: str, cid: str, body: ConversationSave, user: str = Depends(current_user)) -> dict:
    return conversations.save_conversation(pid, cid, [m.model_dump() for m in body.messages], body.title)

@router.patch("/projects/{pid}/conversations/{cid}")
def patch_conv(pid: str, cid: str, body: ConversationPatch, user: str = Depends(current_user)) -> dict:
    if body.title is not None:
        conversations.set_conversation_title(pid, cid, body.title)
    if body.pinned is not None:
        conversations.set_conversation_pinned(pid, cid, body.pinned)
    return {"ok": True}

@router.delete("/projects/{pid}/conversations/{cid}")
def delete_conv(pid: str, cid: str, user: str = Depends(current_user)) -> dict:
    conversations.delete_conversation(pid, cid)
    return {"ok": True}

@router.post("/projects/{pid}/conversations/{cid}/move")
def move_conv(pid: str, cid: str, body: MoveBody, user: str = Depends(current_user)) -> dict:
    return {"ok": conversations.move_conversation(pid, cid, body.dst_project_id)}

@router.get("/conversations")
def list_all(limit: int = 200, user: str = Depends(current_user)) -> list[dict]:
    return conversations.list_all_conversations(limit)
```

- [ ] **Step 6: `backend/app/routes/settings.py`** (move the probe here)
```python
from __future__ import annotations
from fastapi import APIRouter, Depends
from ocd_core import settings
from ..deps import current_user
from ..schemas import SettingsBody

router = APIRouter()

@router.get("/settings")
def get_settings(user: str = Depends(current_user)) -> dict:
    return settings.get_settings()

@router.put("/settings")
def put_settings(body: SettingsBody, user: str = Depends(current_user)) -> dict:
    return settings.save_settings({k: v for k, v in body.model_dump().items() if v is not None})
```
Remove the temporary `get_settings` from `routes/health.py`.

- [ ] **Step 7: Register routers** in `main.py`: `from .routes import health, auth, agent, projects, conversations, settings` + `include_router` for projects/conversations/settings.

- [ ] **Step 8: Run — expect PASS** + full suite. `venv312/Scripts/python.exe -m pytest backend/tests -q`.

- [ ] **Step 9: Commit**
```bash
git add -A
git commit -m "feat(app): REST routes for projects, conversations, settings" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: REST — knowledge + schema + integrations

**Files:**
- Create: `backend/app/routes/knowledge.py`, `schema.py`, `integrations.py`
- Modify: `backend/app/main.py` (routers)
- Create: `backend/tests/test_rest_knowledge_schema_integrations.py`

- [ ] **Step 1: Write failing tests** (`backend/tests/test_rest_knowledge_schema_integrations.py`)
```python
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client(db, monkeypatch):
    # avoid hitting BigQuery/Chroma: stub schema search
    from ocd_core import schema_catalog
    monkeypatch.setattr(schema_catalog, "search_schema", lambda q, active_project=None, top_k=6: f"results for {q}")
    from backend.app.main import app
    return TestClient(app)

def test_schema_search(client):
    r = client.get("/schema/search", params={"q": "users"})
    assert r.status_code == 200 and "users" in r.json()["result"]

def test_integrations_lists(client):
    assert client.get("/plugins").status_code == 200
    assert client.get("/skills").status_code == 200
    assert client.get("/connectors").status_code == 200
    assert client.get("/mcp-servers").status_code == 200

def test_knowledge_upload_and_list(client):
    client.post("/projects", json={"name": "K"})
    files = {"file": ("note.txt", b"hello knowledge", "text/plain")}
    r = client.post("/projects/k/files", files=files)
    assert r.status_code == 200
    listed = client.get("/projects/k/files").json()
    assert any(f["name"] == "note.txt" for f in listed)
```

- [ ] **Step 2: Run — expect FAIL** (routes 404). `venv312/Scripts/python.exe -m pytest backend/tests/test_rest_knowledge_schema_integrations.py -v`

- [ ] **Step 3: `backend/app/routes/schema.py`**
```python
from __future__ import annotations
from fastapi import APIRouter, Depends
from ocd_core import schema_catalog
from ..deps import current_user

router = APIRouter(prefix="/schema")

@router.get("/search")
def search(q: str, project: str | None = None, user: str = Depends(current_user)) -> dict:
    return {"result": schema_catalog.search_schema(q, active_project=project)}

@router.post("/rebuild")
def rebuild(user: str = Depends(current_user)) -> dict:
    n, errors = schema_catalog.ensure_catalog()
    return {"tables": n, "errors": errors}

@router.get("/status")
def status(user: str = Depends(current_user)) -> dict:
    return {"version_ok": schema_catalog._catalog_version_matches()}
```

- [ ] **Step 4: `backend/app/routes/integrations.py`** — thin calls into `ocd_core.integrations` + `ocd_core.skills`:
```python
from __future__ import annotations
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from ocd_core import integrations, skills
from ..deps import current_user

router = APIRouter()

class ConnectorBody(BaseModel):
    name: str
    base_url: str
    header_key: str = ""
    header_value: str = ""

class McpBody(BaseModel):
    name: str
    command: str
    args: list[str] = []

@router.get("/plugins")
def list_plugins(user: str = Depends(current_user)) -> list[dict]:
    return integrations.list_plugins()

@router.get("/skills")
def list_skills(user: str = Depends(current_user)) -> list[dict]:
    return skills.list_skills()

@router.get("/connectors")
def list_connectors(user: str = Depends(current_user)) -> list[dict]:
    return integrations.list_connectors()

@router.post("/connectors")
def add_connector(body: ConnectorBody, user: str = Depends(current_user)) -> dict:
    return integrations.add_connector(body.name, body.base_url, body.header_key, body.header_value)

@router.delete("/connectors/{cid}")
def remove_connector(cid: str, user: str = Depends(current_user)) -> dict:
    integrations.remove_connector(cid)
    return {"ok": True}

@router.post("/connectors/{cid}/test")
def test_connector(cid: str, user: str = Depends(current_user)) -> dict:
    return {"result": integrations.test_connector(cid)}

@router.get("/mcp-servers")
def list_mcp(user: str = Depends(current_user)) -> list[dict]:
    return integrations.list_mcp_servers()

@router.post("/mcp-servers")
def add_mcp(body: McpBody, user: str = Depends(current_user)) -> dict:
    return integrations.add_mcp_server(body.name, body.command, body.args)

@router.delete("/mcp-servers/{sid}")
def remove_mcp(sid: str, user: str = Depends(current_user)) -> dict:
    integrations.remove_mcp_server(sid)
    return {"ok": True}

@router.get("/mcp-servers/{sid}/tools")
def mcp_tools(sid: str, user: str = Depends(current_user)) -> dict:
    return {"tools": integrations.mcp_tools([sid])}
```
NOTE: confirm the exact `integrations` function names/signatures against `backend/ocd_core/integrations.py` (from the Phase-1 harvest: `list_plugins`, `list_connectors`, `add_connector(name,base_url,header_key,header_value)`, `remove_connector(cid)`, `test_connector(cid)`, `list_mcp_servers`, `add_mcp_server(name,command,args)`, `remove_mcp_server(sid)`, `mcp_tools(enabled_ids)`). Adapt arg names if they differ.

- [ ] **Step 5: `backend/app/routes/knowledge.py`** (multipart upload → ingest)
```python
from __future__ import annotations
from fastapi import APIRouter, Depends, UploadFile, File
from ocd_core import knowledge
from ..deps import current_user

router = APIRouter()

@router.post("/projects/{pid}/files")
def upload(pid: str, file: UploadFile = File(...), user: str = Depends(current_user)) -> dict:
    path = knowledge.save_uploaded_file(pid, file.filename, file.file.read())
    chunks = knowledge.ingest_file_to_kb(pid, path)
    return {"ok": True, "name": file.filename, "chunks": chunks}

@router.get("/projects/{pid}/files")
def list_files(pid: str, user: str = Depends(current_user)) -> list[dict]:
    return knowledge.list_project_files(pid)
```
NOTE: confirm `knowledge.save_uploaded_file(pid, filename, data) -> Path` and `knowledge.ingest_file_to_kb(pid, path) -> int` and `knowledge.list_project_files(pid) -> [{name,size,...}]` signatures; adapt. Ingest may touch Chroma — the test uses the `db` fixture (CHROMA_PATH isolated to tmp) so a real lightweight ingest is fine; if ingest is slow/network, monkeypatch `knowledge.ingest_file_to_kb` to return an int in the test.

- [ ] **Step 6: Register routers** in `main.py`: add `knowledge, schema, integrations` to the import + `include_router` calls.

- [ ] **Step 7: Run — expect PASS** + full suite. `venv312/Scripts/python.exe -m pytest backend/tests -q`.

- [ ] **Step 8: Commit**
```bash
git add -A
git commit -m "feat(app): REST routes for knowledge, schema, integrations — backend surface complete" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Appendix A: sanity check (run after each task)

```bash
venv312/Scripts/python.exe -m pytest backend/tests -q                                  # all green (SQLite, no network)
venv312/Scripts/python.exe -c "from backend.app.main import app; print('app routes:', len(app.routes))"
venv312/Scripts/python.exe -c "import sys; sys.path.insert(0,'aj360_app'); from aj360_app import core, agent, integrations; import aj360_app.aj360_app as ui; print('reflex unchanged OK')"
```
To run the service for manual testing: `venv312/Scripts/python.exe -m uvicorn backend.app.main:app --reload` then `GET http://127.0.0.1:8000/healthz`.

## Self-review

- **Spec coverage:** auth extraction (T1, spec §4), app skeleton + optional-auth + login + health (T2, §4), allowlist hardening to parsed referenced_tables (T3, §7), agent SSE endpoint + rate-limit + audit + SSE mocking strategy (T4, §5/§7/§8), REST projects/conversations/settings with schemas (T5, §6), REST knowledge/schema/integrations (T6, §6). Sync-routes-threadpool (all REST `def`), agent route `async` (T4). ✓
- **Placeholder scan:** the per-task NOTEs ("confirm the real signatures against ocd_core.X and adapt") are explicit verification instructions for verbatim/thin-wrapper code, not hidden TODOs — each names the exact source module + the expected signature. No "TBD"/"handle edge cases".
- **Type/name consistency:** `current_user` dependency (T2) used by every route (T2/T4/T5/T6); `format_event` (T4 sse.py) used in agent.py; `AgentTurnRequest`/`AgentOptions`/`Message`/the CRUD bodies (schemas.py) used consistently; `tables_off_allowlist(referenced_tables, allowlist)` (T3) used by `execute_sql` (T3). `auth.auth_enabled`/`verify_token`/`make_token`/`credentials_ok` (T1) used by deps.py + routes/auth.py.
