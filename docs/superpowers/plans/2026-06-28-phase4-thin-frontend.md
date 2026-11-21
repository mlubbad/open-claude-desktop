# Phase 4 — Thin Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Reflex app into a thin HTTP/SSE client that imports zero `ocd_core` code, talking to the FastAPI backend over REST + SSE.

**Architecture:** A typed `api_client` (httpx + httpx-sse) replaces every in-process `core`/`agent`/`integrations` call in `state.py`. The agent turn streams over SSE preserving the real event vocabulary, so the existing transcript renderer is reused verbatim. Six missing backend endpoints are added; two pure formatters become local frontend helpers; three skill/tool calls disappear (resolved server-side). The package then moves to `frontend/` and the 1295-line UI monolith splits into focused component modules.

**Tech Stack:** Python 3.12, Reflex, httpx, httpx-sse, respx + pytest-asyncio (tests), FastAPI (backend endpoints), sse-starlette.

**Spec:** `docs/superpowers/specs/2026-06-28-phase4-thin-frontend-design.md`

**Test commands:**
- Backend: `venv312/Scripts/python.exe -m pytest backend/tests -q`
- Frontend (pre-move): `cd legacy_frontend && ../venv312/Scripts/python.exe -m pytest tests -q`
- Frontend (post-move): `cd frontend && ../venv312/Scripts/python.exe -m pytest tests -q`

**Conventions:** `git mv` to preserve history. Every endpoint added gets a backend test that mocks the `ocd_core` function (no live GLM/BigQuery/Postgres). Frontend api_client tests use respx (no live backend).

---

## File Structure

**Created:**
- `legacy_frontend/api_client.py` — typed async HTTP/SSE client (the contract layer)
- `legacy_frontend/format.py` — local pure formatters (`fmt_bytes`, `strip_answer_label`)
- `legacy_frontend/tests/__init__.py`, `legacy_frontend/tests/conftest.py`, `legacy_frontend/tests/test_api_client.py`, `legacy_frontend/tests/test_format.py`
- `legacy_frontend/pytest.ini` — `asyncio_mode = auto`
- `legacy_frontend/components/__init__.py` and component modules (Task 6)
- `backend/app/routes/sql.py` — new `/sql/execute` route

**Modified:**
- `backend/app/routes/projects.py` — add `?view=card` to `GET /projects`
- `backend/app/routes/conversations.py` — add `POST /conversations/title`
- `backend/app/routes/knowledge.py` — add `GET /files`
- `backend/app/routes/integrations.py` — add `POST /mcp-servers/demo`, `POST /connectors/github`
- `backend/app/main.py` — register the `sql` router; tighten CORS (Task 7)
- `backend/app/schemas.py` — add request bodies for the new endpoints
- `legacy_frontend/state.py` — route all domain calls through `api_client`; delete shim imports
- `legacy_legacy_frontend.py` — reduce to page assembly + routing (Task 6)
- `legacy_frontend/requirements.txt` — `reflex`, `httpx`, `httpx-sse` (drop ocd_core/editable backend)

**Deleted (Task 5):**
- `legacy_frontend/core.py`, `agent.py`, `integrations.py` (re-export shims)

**Moved (Task 4):** entire `legacy_frontend/` tree → `frontend/`.

---

## Task 1: Frontend `api_client.py` + test harness

This is the contract everything else builds on. Tests use respx and run fully offline.

**Files:**
- Create: `legacy_frontend/api_client.py`
- Create: `legacy_frontend/tests/__init__.py`, `legacy_frontend/tests/conftest.py`, `legacy_frontend/tests/test_api_client.py`
- Create: `legacy_frontend/pytest.ini`
- Modify: `legacy_frontend/requirements.txt`

- [ ] **Step 1: Install test deps into the dev venv**

Run:
```bash
venv312/Scripts/python.exe -m pip install httpx-sse respx pytest-asyncio
```
Expected: successful install (httpx and pytest already present from `backend[dev]`).

- [ ] **Step 2: Add the pytest config for async tests**

Create `legacy_frontend/pytest.ini`:
```ini
[pytest]
asyncio_mode = auto
testpaths = tests
addopts = -q
```

- [ ] **Step 3: Write the failing tests**

Create `legacy_frontend/tests/__init__.py` (empty).

Create `legacy_frontend/tests/conftest.py`:
```python
import pytest

import legacy_frontend.api_client as api_client


@pytest.fixture(autouse=True)
def reset_client():
    """Each test starts with a clean base URL + no auth token."""
    api_client.configure(base_url="http://test", token=None)
    yield
    api_client.configure(base_url="http://test", token=None)
```

Create `legacy_frontend/tests/test_api_client.py`:
```python
import json

import httpx
import pytest
import respx

import legacy_frontend.api_client as api_client


def _sse(*events: dict) -> bytes:
    """Serialize event dicts as an SSE body the way backend/app/sse.py does."""
    frames = []
    for ev in events:
        frames.append(f"event: {ev['type']}\ndata: {json.dumps(ev)}\n")
    return ("\n".join(frames) + "\n").encode()


@respx.mock
async def test_login_returns_token_and_sets_bearer():
    route = respx.post("http://test/auth/login").mock(
        return_value=httpx.Response(200, json={"token": "tok-123"}))
    token = await api_client.login("alice", "pw")
    assert token == "tok-123"
    assert json.loads(route.calls.last.request.content) == {"username": "alice", "password": "pw"}

    # Subsequent calls now carry the Bearer header.
    proj = respx.get("http://test/projects").mock(
        return_value=httpx.Response(200, json=[]))
    await api_client.list_projects()
    assert proj.calls.last.request.headers["authorization"] == "Bearer tok-123"


@respx.mock
async def test_anonymous_has_no_auth_header():
    route = respx.get("http://test/projects").mock(
        return_value=httpx.Response(200, json=[{"id": "p1"}]))
    out = await api_client.list_projects()
    assert out == [{"id": "p1"}]
    assert "authorization" not in route.calls.last.request.headers


@respx.mock
async def test_list_project_cards_hits_view_param():
    route = respx.get("http://test/projects", params={"view": "card"}).mock(
        return_value=httpx.Response(200, json=[{"id": "p1", "name": "P", "desc": "d",
                                                "updated": "today", "href": "/project/p1"}]))
    cards = await api_client.list_project_cards()
    assert cards[0]["href"] == "/project/p1"
    assert route.called


@respx.mock
async def test_get_project_memory_returns_tuple():
    respx.get("http://test/projects/p1/memory").mock(
        return_value=httpx.Response(200, json={"content": "notes", "updated_rel": "2h ago"}))
    text, rel = await api_client.get_project_memory("p1")
    assert text == "notes"
    assert rel == "2h ago"


@respx.mock
async def test_upload_file_sends_multipart():
    route = respx.post("http://test/projects/p1/files").mock(
        return_value=httpx.Response(200, json={"ok": True, "name": "a.csv", "chunks": 3}))
    out = await api_client.upload_file("p1", "a.csv", b"col\n1\n")
    assert out["chunks"] == 3
    assert route.calls.last.request.headers["content-type"].startswith("multipart/form-data")


@respx.mock
async def test_execute_sql_posts_body():
    route = respx.post("http://test/sql/execute").mock(
        return_value=httpx.Response(200, json={"ok": True, "rows": [], "columns": [],
                                               "total_rows": 0, "bytes": 0, "agent_text": ""}))
    out = await api_client.execute_sql("SELECT 1", "p1")
    assert out["ok"] is True
    assert json.loads(route.calls.last.request.content) == {"sql": "SELECT 1", "project": "p1"}


@respx.mock
async def test_non_2xx_raises_apierror():
    respx.get("http://test/projects/missing").mock(return_value=httpx.Response(404, json={"detail": "not found"}))
    with pytest.raises(api_client.ApiError) as ei:
        await api_client.get_project("missing")
    assert ei.value.status == 404


@respx.mock
async def test_run_agent_stream_parses_real_vocab_and_stops_on_done():
    body = _sse(
        {"type": "think_open", "phase": "plan"},
        {"type": "delta", "scope": "think", "text": "Let me check"},
        {"type": "think_close", "elapsed": 2},
        {"type": "tool", "id": "t1", "name": "run_sql", "icon": "database",
         "label_running": "Running", "label_done": "Ran", "input": "SELECT 1"},
        {"type": "tool_result", "id": "t1", "summary": "1 row"},
        {"type": "table", "total": 1, "bytes": 10, "columns": ["n"], "rows": [{"n": 1}]},
        {"type": "answer_open"},
        {"type": "delta", "scope": "answer", "text": "The answer"},
        {"type": "done"},
    )
    respx.post("http://test/agent/turn").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body))

    got = [ev async for ev in api_client.run_agent_stream({"goal": "hi", "model": "glm-4-plus"})]
    types = [e["type"] for e in got]
    assert types == ["think_open", "delta", "think_close", "tool", "tool_result",
                     "table", "answer_open", "delta"]   # 'done' consumed, not yielded
    assert got[3]["id"] == "t1" and got[3]["icon"] == "database"
    assert got[5]["columns"] == ["n"]


@respx.mock
async def test_run_agent_stream_yields_error_frame():
    body = _sse({"type": "error", "text": "boom"}, {"type": "done"})
    respx.post("http://test/agent/turn").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body))
    got = [ev async for ev in api_client.run_agent_stream({"goal": "x", "model": "m"})]
    assert got == [{"type": "error", "text": "boom"}]
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `cd legacy_frontend && ../venv312/Scripts/python.exe -m pytest tests/test_api_client.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'legacy_frontend.api_client'`.

- [ ] **Step 5: Implement `api_client.py`**

Create `legacy_frontend/api_client.py`:
```python
"""Typed async HTTP/SSE client for the OCD FastAPI backend.

The frontend's ONLY link to the backend. No ocd_core imports anywhere.
The agent turn preserves the backend's real event vocabulary end to end
(think_open/think_close/delta/answer_open/answer_to_think/tool/tool_result/
tool_error/table/sources/error) so state.py's renderer is reused verbatim.
"""
from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator

import httpx
from httpx_sse import aconnect_sse

_BASE: str = os.environ.get("OCD_API_URL", "http://localhost:8000")
_TOKEN: str | None = None


class ApiError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


def configure(base_url: str | None = None, token: str | None = ...) -> None:
    """Set the base URL and/or auth token. Pass token=None to clear it."""
    global _BASE, _TOKEN
    if base_url is not None:
        _BASE = base_url
    if token is not ...:
        _TOKEN = token


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    h = dict(extra or {})
    if _TOKEN:
        h["Authorization"] = f"Bearer {_TOKEN}"
    return h


async def _request(method: str, path: str, **kw) -> httpx.Response:
    async with httpx.AsyncClient(base_url=_BASE, timeout=60.0) as client:
        resp = await client.request(method, path, headers=_headers(kw.pop("headers", None)), **kw)
    if resp.status_code >= 400:
        detail = ""
        try:
            detail = resp.json().get("detail", "")
        except Exception:
            detail = resp.text
        raise ApiError(resp.status_code, detail)
    return resp


async def _get(path: str, **kw) -> object:
    return (await _request("GET", path, **kw)).json()


async def _post(path: str, json_body: object | None = None, **kw) -> object:
    return (await _request("POST", path, json=json_body, **kw)).json()


async def _put(path: str, json_body: object) -> object:
    return (await _request("PUT", path, json=json_body)).json()


async def _patch(path: str, json_body: object) -> object:
    return (await _request("PATCH", path, json=json_body)).json()


async def _delete(path: str) -> object:
    return (await _request("DELETE", path)).json()


# ----------------------------- auth ----------------------------- #
async def login(username: str, password: str) -> str:
    data = await _post("/auth/login", {"username": username, "password": password})
    token = data["token"]
    configure(token=token)
    return token


async def health() -> dict:
    return await _get("/health")  # type: ignore[return-value]


# --------------------------- projects --------------------------- #
async def list_projects() -> list[dict]:
    return await _get("/projects")  # type: ignore[return-value]


async def list_project_cards() -> list[dict]:
    return await _get("/projects", params={"view": "card"})  # type: ignore[return-value]


async def create_project(name: str) -> dict:
    return await _post("/projects", {"name": name})  # type: ignore[return-value]


async def get_project(pid: str) -> dict:
    return await _get(f"/projects/{pid}")  # type: ignore[return-value]


async def delete_project(pid: str) -> bool:
    return bool((await _delete(f"/projects/{pid}"))["ok"])


async def get_project_instructions(pid: str) -> str:
    return (await _get(f"/projects/{pid}/instructions"))["content"]


async def save_project_instructions(pid: str, content: str) -> None:
    await _put(f"/projects/{pid}/instructions", {"content": content})


async def get_project_memory(pid: str) -> tuple[str, str]:
    d = await _get(f"/projects/{pid}/memory")
    return d["content"], d["updated_rel"]


async def save_project_memory(pid: str, content: str) -> None:
    await _put(f"/projects/{pid}/memory", {"content": content})


async def project_capacity(pid: str) -> dict:
    return await _get(f"/projects/{pid}/capacity")  # type: ignore[return-value]


# ------------------------ conversations ------------------------- #
async def list_conversations(pid: str) -> list[dict]:
    return await _get(f"/projects/{pid}/conversations")  # type: ignore[return-value]


async def list_all_conversations(limit: int = 200) -> list[dict]:
    return await _get("/conversations", params={"limit": limit})  # type: ignore[return-value]


async def create_conversation(pid: str, first_message: str) -> dict:
    return await _post(f"/projects/{pid}/conversations", {"first_message": first_message})  # type: ignore[return-value]


async def get_conversation(pid: str, cid: str) -> dict:
    return await _get(f"/projects/{pid}/conversations/{cid}")  # type: ignore[return-value]


async def save_conversation(pid: str, cid: str, messages: list[dict], title: str | None = None) -> dict:
    return await _put(f"/projects/{pid}/conversations/{cid}",
                      {"messages": messages, "title": title})  # type: ignore[return-value]


async def set_conversation_title(pid: str, cid: str, title: str) -> None:
    await _patch(f"/projects/{pid}/conversations/{cid}", {"title": title})


async def set_conversation_pinned(pid: str, cid: str, pinned: bool) -> None:
    await _patch(f"/projects/{pid}/conversations/{cid}", {"pinned": pinned})


async def move_conversation(pid: str, cid: str, dst_project_id: str) -> bool:
    return bool((await _post(f"/projects/{pid}/conversations/{cid}/move",
                             {"dst_project_id": dst_project_id}))["ok"])


async def delete_conversation(pid: str, cid: str) -> None:
    await _delete(f"/projects/{pid}/conversations/{cid}")


async def generate_conversation_title(first_message: str) -> str:
    return (await _post("/conversations/title", {"first_message": first_message}))["title"]


# --------------------------- knowledge -------------------------- #
async def list_project_files(pid: str) -> list[dict]:
    return await _get(f"/projects/{pid}/files")  # type: ignore[return-value]


async def list_all_files(limit: int = 500) -> list[dict]:
    return await _get("/files", params={"limit": limit})  # type: ignore[return-value]


async def upload_file(pid: str, filename: str, data: bytes) -> dict:
    files = {"file": (filename, data)}
    return (await _request("POST", f"/projects/{pid}/files", files=files)).json()


# ----------------------------- sql ------------------------------ #
async def execute_sql(sql: str, project: str | None = None) -> dict:
    return await _post("/sql/execute", {"sql": sql, "project": project})  # type: ignore[return-value]


# ---------------------------- settings -------------------------- #
async def get_settings() -> dict:
    return await _get("/settings")  # type: ignore[return-value]


async def save_settings(patch: dict) -> dict:
    return await _put("/settings", patch)  # type: ignore[return-value]


# -------------------------- integrations ------------------------ #
async def list_plugins() -> list[dict]:
    return await _get("/plugins")  # type: ignore[return-value]


async def list_skills() -> list[dict]:
    return await _get("/skills")  # type: ignore[return-value]


async def list_connectors() -> list[dict]:
    return await _get("/connectors")  # type: ignore[return-value]


async def add_connector(name: str, base_url: str, header_key: str = "", header_value: str = "") -> dict:
    return await _post("/connectors", {"name": name, "base_url": base_url,
                                       "header_key": header_key, "header_value": header_value})  # type: ignore[return-value]


async def remove_connector(cid: str) -> None:
    await _delete(f"/connectors/{cid}")


async def test_connector(cid: str) -> str:
    return (await _post(f"/connectors/{cid}/test"))["result"]


async def import_github_repo(repo_url: str, project_id: str) -> dict:
    return await _post("/connectors/github", {"repo_url": repo_url, "project_id": project_id})  # type: ignore[return-value]


async def list_mcp_servers() -> list[dict]:
    return await _get("/mcp-servers")  # type: ignore[return-value]


async def add_mcp_server(name: str, command: str, args: list[str]) -> dict:
    return await _post("/mcp-servers", {"name": name, "command": command, "args": args})  # type: ignore[return-value]


async def add_demo_mcp_server() -> dict:
    return await _post("/mcp-servers/demo")  # type: ignore[return-value]


async def remove_mcp_server(sid: str) -> None:
    await _delete(f"/mcp-servers/{sid}")


# ----------------------------- schema --------------------------- #
async def search_schema(q: str, project: str | None = None) -> str:
    return (await _get("/schema/search", params={"q": q, "project": project}))["result"]


# -------------------------- agent (SSE) ------------------------- #
async def run_agent_stream(req: dict) -> AsyncIterator[dict]:
    """Stream a turn. Yields the backend's event dicts unchanged; stops on `done`."""
    async with httpx.AsyncClient(base_url=_BASE, timeout=None) as client:
        async with aconnect_sse(client, "POST", "/agent/turn",
                                json=req, headers=_headers()) as es:
            async for sse in es.aiter_sse():
                ev = json.loads(sse.data)
                if ev.get("type") == "done":
                    return
                yield ev
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd legacy_frontend && ../venv312/Scripts/python.exe -m pytest tests/test_api_client.py -q`
Expected: PASS (9 tests).

- [ ] **Step 7: Update frontend runtime deps**

Edit `legacy_frontend/requirements.txt` to contain exactly (preserve any reflex version pin already present):
```
reflex
httpx
httpx-sse
```
(Remove any `-e ../backend` / `ocd_core` line — the frontend no longer imports the backend.)

- [ ] **Step 8: Commit**

```bash
git add legacy_frontend/api_client.py legacy_frontend/tests legacy_frontend/pytest.ini legacy_frontend/requirements.txt
git commit -m "feat(frontend): typed httpx/SSE api_client + respx tests (Phase 4 Task 1)"
```

---

## Task 2: Backend — six new endpoints

Each closes a gap where `state.py` called `ocd_core` with no REST route. All hermetic — mock the `ocd_core` function.

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routes/projects.py`, `conversations.py`, `knowledge.py`, `integrations.py`
- Create: `backend/app/routes/sql.py`
- Modify: `backend/app/main.py` (register `sql` router)
- Test: `backend/tests/test_new_endpoints.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_new_endpoints.py`:
```python
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_projects_card_view():
    fake_projects = [{"id": "p1", "name": "P1", "created_at": "2026-01-01"}]
    fake_card = {"id": "p1", "name": "P1", "updated": "Jan 1", "desc": "d", "href": "/project/p1"}
    with patch("app.routes.projects.projects.list_projects", return_value=fake_projects), \
         patch("app.routes.projects.projects.project_card_view", return_value=fake_card):
        r = client.get("/projects", params={"view": "card"})
    assert r.status_code == 200
    assert r.json() == [fake_card]


def test_projects_plain_view_unchanged():
    with patch("app.routes.projects.projects.list_projects", return_value=[{"id": "p1"}]):
        r = client.get("/projects")
    assert r.json() == [{"id": "p1"}]


def test_conversation_title():
    with patch("app.routes.conversations.conversations.generate_conversation_title",
               return_value="Quarterly Revenue") as m:
        r = client.post("/conversations/title", json={"first_message": "how much did we make"})
    assert r.json() == {"title": "Quarterly Revenue"}
    m.assert_called_once_with("how much did we make")


def test_list_all_files():
    rows = [{"name": "a.csv", "project_id": "p1", "project_name": "P1"}]
    with patch("app.routes.knowledge.knowledge.list_all_files", return_value=rows) as m:
        r = client.get("/files", params={"limit": 50})
    assert r.json() == rows
    m.assert_called_once_with(50)


def test_sql_execute():
    result = {"ok": True, "rows": [{"n": 1}], "columns": ["n"], "total_rows": 1,
              "bytes": 10, "agent_text": "[1 rows]"}
    with patch("app.routes.sql.bigquery.execute_sql", return_value=result) as m:
        r = client.post("/sql/execute", json={"sql": "SELECT 1", "project": "p1"})
    assert r.json() == result
    m.assert_called_once_with("SELECT 1", "p1")


def test_add_demo_mcp_server():
    with patch("app.routes.integrations.integrations.add_demo_mcp_server",
               return_value={"id": "m1", "name": "Demo Connector"}) as m:
        r = client.post("/mcp-servers/demo")
    assert r.json()["name"] == "Demo Connector"
    m.assert_called_once_with()


def test_import_github_repo():
    with patch("app.routes.integrations.integrations.import_github_repo",
               return_value=(7, "")) as m:
        r = client.post("/connectors/github", json={"repo_url": "owner/repo", "project_id": "p1"})
    assert r.json() == {"chunks": 7, "message": ""}
    m.assert_called_once_with("owner/repo", "p1")
```

- [ ] **Step 2: Run to verify failure**

Run: `venv312/Scripts/python.exe -m pytest backend/tests/test_new_endpoints.py -q`
Expected: FAIL (404s — routes don't exist yet).

- [ ] **Step 3: Add request schemas**

Append to `backend/app/schemas.py`:
```python
class TitleRequest(BaseModel):
    first_message: str


class SqlExecuteRequest(BaseModel):
    sql: str
    project: str | None = None


class GithubImportRequest(BaseModel):
    repo_url: str
    project_id: str
```

- [ ] **Step 4: Add `?view=card` to projects list**

In `backend/app/routes/projects.py`, replace the `list_projects` route:
```python
@router.get("")
def list_projects(view: str = "", user: str = Depends(current_user)) -> list[dict]:
    rows = projects.list_projects()
    if view == "card":
        return [projects.project_card_view(p) for p in rows]
    return rows
```

- [ ] **Step 5: Add the conversation-title route**

In `backend/app/routes/conversations.py`, add the import `from ..schemas import ... , TitleRequest` and append:
```python
@router.post("/conversations/title")
def conversation_title(body: TitleRequest, user: str = Depends(current_user)) -> dict:
    return {"title": conversations.generate_conversation_title(body.first_message)}
```

- [ ] **Step 6: Add the all-files route**

In `backend/app/routes/knowledge.py`, append:
```python
@router.get("/files")
def all_files(limit: int = 500, user: str = Depends(current_user)) -> list[dict]:
    return knowledge.list_all_files(limit)
```

- [ ] **Step 7: Create the SQL route**

Create `backend/app/routes/sql.py`:
```python
from __future__ import annotations

from fastapi import APIRouter, Depends
from ocd_core import bigquery

from ..deps import current_user
from ..schemas import SqlExecuteRequest

router = APIRouter(prefix="/sql")


@router.post("/execute")
def execute(body: SqlExecuteRequest, user: str = Depends(current_user)) -> dict:
    return bigquery.execute_sql(body.sql, body.project)
```

- [ ] **Step 8: Add the MCP-demo and GitHub-import routes**

In `backend/app/routes/integrations.py`, add `from ..schemas import GithubImportRequest` and append:
```python
@router.post("/mcp-servers/demo")
def add_demo_mcp(user: str = Depends(current_user)) -> dict:
    return integrations.add_demo_mcp_server()


@router.post("/connectors/github")
def import_github(body: GithubImportRequest, user: str = Depends(current_user)) -> dict:
    count, message = integrations.import_github_repo(body.repo_url, body.project_id)
    return {"chunks": count, "message": message}
```

- [ ] **Step 9: Register the SQL router**

In `backend/app/main.py`, import and include it alongside the other routers:
```python
from .routes import sql
app.include_router(sql.router)
```

- [ ] **Step 10: Run the tests to verify they pass**

Run: `venv312/Scripts/python.exe -m pytest backend/tests/test_new_endpoints.py -q`
Expected: PASS (7 tests).

- [ ] **Step 11: Run the full backend suite (no regressions)**

Run: `venv312/Scripts/python.exe -m pytest backend/tests -q`
Expected: PASS (98 prior + 7 new = 105).

- [ ] **Step 12: Commit**

```bash
git add backend/app/routes backend/app/main.py backend/app/schemas.py backend/tests/test_new_endpoints.py
git commit -m "feat(api): add sql/exec, files, conv-title, gh-import, mcp-demo, project cards (Phase 4 Task 2)"
```

---

## Task 3: Frontend `format.py` local helpers

Two pure formatters move into the frontend so `state.py` needs no `ocd_core`. They are copied verbatim from `ocd_core.util.fmt_bytes` and `ocd_core.agent._strip_answer_label`.

**Files:**
- Create: `legacy_frontend/format.py`
- Test: `legacy_frontend/tests/test_format.py`

- [ ] **Step 1: Capture the source-of-truth implementations**

Read the originals and copy their exact bodies:
- `backend/ocd_core/util.py:25` (`fmt_bytes`)
- `backend/ocd_core/agent.py` (`_strip_answer_label`) — search for `def _strip_answer_label`.

- [ ] **Step 2: Write the failing tests**

Create `legacy_frontend/tests/test_format.py`:
```python
from legacy_frontend.format import fmt_bytes, strip_answer_label


def test_fmt_bytes_scales():
    assert fmt_bytes(0) == "0 B"
    assert fmt_bytes(1024) == "1.0 KB"
    assert fmt_bytes(1024 * 1024) == "1.0 MB"


def test_strip_answer_label_removes_prefix():
    # Whatever the original strips (e.g. a leading "Answer:"/"Final:" label),
    # plain text must pass through unchanged.
    assert strip_answer_label("Just the answer.") == "Just the answer."
```

> Implementer note: adjust the exact assertion strings in `test_fmt_bytes_scales` / `test_strip_answer_label_removes_prefix` to match the **verbatim** behavior of the two source functions you copied in Step 1 (the source is the contract). Do not invent new formatting.

- [ ] **Step 3: Run to verify failure**

Run: `cd legacy_frontend && ../venv312/Scripts/python.exe -m pytest tests/test_format.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'legacy_frontend.format'`.

- [ ] **Step 4: Create `format.py`**

Create `legacy_frontend/format.py` with the two functions copied verbatim from Step 1 (no `ocd_core` import), e.g.:
```python
"""Pure presentation formatters (no I/O, no ocd_core) — copied from the backend
util/agent helpers so the thin frontend stays dependency-free."""
from __future__ import annotations


def fmt_bytes(n) -> str:
    # <verbatim body from ocd_core/util.py:fmt_bytes>
    ...


def strip_answer_label(text: str) -> str:
    # <verbatim body from ocd_core/agent.py:_strip_answer_label>
    ...
```

- [ ] **Step 5: Run to verify pass**

Run: `cd legacy_frontend && ../venv312/Scripts/python.exe -m pytest tests/test_format.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add legacy_frontend/format.py legacy_frontend/tests/test_format.py
git commit -m "feat(frontend): local pure formatters fmt_bytes/strip_answer_label (Phase 4 Task 3)"
```

---

## Task 4: Move the package to `frontend/`

Pure structural move; history preserved with `git mv`.

**Files:** entire `legacy_frontend/` → `frontend/`.

- [ ] **Step 1: Move the tree**

```bash
git mv legacy_frontend frontend
```

- [ ] **Step 2: Verify the package + tests still resolve**

Run:
```bash
cd frontend && ../venv312/Scripts/python.exe -m pytest tests -q
```
Expected: PASS (api_client + format tests, 11 total). No import path changed — the inner package is still `legacy_frontend`, now at `legacy_frontend/`.

- [ ] **Step 3: Confirm Reflex config is intact**

Confirm `frontend/rxconfig.py` still sets `app_name="legacy_frontend"` and `frontend/assets/` moved. (No edit expected; just verify.)

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(frontend): move legacy_frontend/ -> frontend/ (Phase 4 Task 4)"
```

---

## Task 5: Decouple `state.py` from `ocd_core`

Route every domain call through `api_client`; the agent loop swaps its source only. Work from `legacy_frontend/state.py`.

**Files:**
- Modify: `legacy_frontend/state.py`
- Delete: `legacy_frontend/core.py`, `agent.py`, `integrations.py`

- [ ] **Step 1: Swap the imports**

In `legacy_frontend/state.py`, replace:
```python
from . import core
from . import agent
from . import integrations
```
with:
```python
from . import api_client
from . import format as fmt
```

- [ ] **Step 2: Rewrite the agent loop source + add the request builder**

Replace the agent-turn block (currently `legacy_frontend/state.py` around the `async for ev in agent.run_turn(...)` call) so the source is the SSE client and the skill/tool resolution is dropped (server does it). The event-switch body below it is **unchanged**.

```python
def _build_turn_request(self, goal: str, pid: str) -> dict:
    """Assemble the AgentTurnRequest the backend expects."""
    return {
        "project_id": pid or None,
        "goal": goal,
        "history": self._chat_history(),
        "model": self.model,
        "effort": self.effort,
        "options": {
            "web_search": self.web_search_on,
            "research": self.research_on,
            "web_fetch": self.web_fetch_on,
            "code_exec": self.code_exec_on,
            "bash": self.bash_on,
            "text_editor": self.text_editor_on,
            "memory": self.memory_on,
        },
        "enabled_plugins": list(self.enabled_plugins),
        "enabled_connectors": list(self.enabled_connectors),
        "enabled_mcp": list(self.enabled_mcp),
    }
```

And in `_run_agent`, replace everything from `history = self._chat_history()` through the start of the `async for` with:
```python
self.is_running = True
yield
try:
    async for ev in api_client.run_agent_stream(self._build_turn_request(goal, pid)):
        t = ev["type"]
        # ... (UNCHANGED event switch: thought/verify/delta/think_open/...) ...
        yield
except Exception as e:
    self.messages.append({"role": "assistant", "content": f"Agent error: {e}",
                          "kind": "error"})
self.is_running = False
```
> Remove the now-dead lines that computed `proj_instr`, `skill_name`, `skill_instr`, and `extra_tools` (these are resolved server-side). Inside the switch, the one `core.fmt_bytes(...)` call in the `table` branch becomes `fmt.fmt_bytes(...)`.

- [ ] **Step 3: Convert the table branch + persistence to api_client**

In the `table` branch: `cap = f"**{ev['total']} rows · {fmt.fmt_bytes(ev['bytes'])} scanned**"`.

The post-stream persistence becomes async:
```python
await api_client.save_conversation(pid, cid, self.messages, self.conv_title or None)
yield
if first_turn and pid and cid:
    try:
        title = await api_client.generate_conversation_title(goal)
        if title:
            ...
```
(Drop the `asyncio.to_thread(core.generate_conversation_title, ...)` wrapper — the client call is already async/non-blocking.)

- [ ] **Step 4: Mechanically convert the remaining call sites**

Replace each remaining `core.X(...)` / `integrations.X(...)` with `await api_client.X(...)`, making the enclosing event handler `async` where it is not already. Use this exact mapping (every site from the spec's §5.1/§6):

| old | new |
|---|---|
| `core.list_projects()` | `await api_client.list_projects()` |
| `core.project_card_view(p)` over a list | `await api_client.list_project_cards()` (fetch cards directly; drop the per-item loop) |
| `core.get_project(pid)` | `await api_client.get_project(pid)` |
| `core.create_project(name)` | `await api_client.create_project(name)` |
| `core.delete_project(pid)` | `await api_client.delete_project(pid)` |
| `core.get_project_instructions(pid)` | `await api_client.get_project_instructions(pid)` |
| `core.save_project_instructions(pid, t)` | `await api_client.save_project_instructions(pid, t)` |
| `core.get_project_memory(pid)` | `await api_client.get_project_memory(pid)` |
| `core.project_capacity(pid)` | `await api_client.project_capacity(pid)` |
| `core.list_conversations(pid)` | `await api_client.list_conversations(pid)` |
| `core.list_all_conversations()` | `await api_client.list_all_conversations()` |
| `core.create_conversation(pid, m)` | `await api_client.create_conversation(pid, m)` |
| `core.get_conversation(pid, cid)` | `await api_client.get_conversation(pid, cid)` |
| `core.save_conversation(...)` | `await api_client.save_conversation(...)` |
| `core.set_conversation_title(...)` | `await api_client.set_conversation_title(...)` |
| `core.set_conversation_pinned(...)` | `await api_client.set_conversation_pinned(...)` |
| `core.move_conversation(...)` | `await api_client.move_conversation(...)` |
| `core.delete_conversation(...)` | `await api_client.delete_conversation(...)` |
| `core.list_project_files(pid)` | `await api_client.list_project_files(pid)` |
| `core.list_all_files()` | `await api_client.list_all_files()` |
| `core.save_uploaded_file(...)` + `core.ingest_file_to_kb(...)` | `await api_client.upload_file(pid, name, data)` (one call) |
| `core.execute_sql(sql, pid)` | `await api_client.execute_sql(sql, pid)` |
| `core.get_settings()` | `await api_client.get_settings()` |
| `core.save_settings(patch)` | `await api_client.save_settings(patch)` |
| `integrations.list_plugins()` | `await api_client.list_plugins()` |
| `integrations.list_skills()` | `await api_client.list_skills()` |
| `integrations.list_connectors()` | `await api_client.list_connectors()` |
| `integrations.add_connector(...)` | `await api_client.add_connector(...)` |
| `integrations.remove_connector(cid)` | `await api_client.remove_connector(cid)` |
| `integrations.test_connector(cid)` | `await api_client.test_connector(cid)` |
| `integrations.list_mcp_servers()` | `await api_client.list_mcp_servers()` |
| `integrations.add_mcp_server(...)` | `await api_client.add_mcp_server(...)` |
| `integrations.add_demo_mcp_server()` | `await api_client.add_demo_mcp_server()` |
| `integrations.remove_mcp_server(sid)` | `await api_client.remove_mcp_server(sid)` |
| `integrations.import_github_repo(url, pid)` | `await api_client.import_github_repo(url, pid)` (returns `{chunks, message}`) |
| `core.fmt_bytes(n)` | `fmt.fmt_bytes(n)` |
| `agent._strip_answer_label(t)` | `fmt.strip_answer_label(t)` |
| `integrations.matching_skill(goal)` | **delete** (server resolves the skill) |
| `integrations.get_skill(name)` | **delete** (server resolves the skill) |
| `integrations.agent_tools(...)` | **delete** (server assembles tools) |

> `import_github_repo` previously returned `(count, error)`; the client now returns `{"chunks", "message"}`. Update the one call site that unpacked the tuple to read `res["chunks"]` / `res["message"]`.

- [ ] **Step 5: Delete the shims**

```bash
git rm legacy_frontend/core.py legacy_frontend/agent.py legacy_frontend/integrations.py
```

- [ ] **Step 6: Verify no `ocd_core` leakage remains**

Run (Grep tool or):
```bash
grep -rnE "ocd_core|from \. import (core|agent|integrations)|core\.|integrations\.|\bagent\." legacy_frontend/state.py
```
Expected: no matches (the only `agent`-ish token left should be none; `api_client`/`fmt` only).

- [ ] **Step 7: Verify the app still compiles**

Run:
```bash
cd frontend && REFLEX_USE_NPM=true ../venv312/Scripts/python.exe -c "import legacy_frontend.legacy_frontend"
```
Expected: imports cleanly (no `ModuleNotFoundError`, no `ocd_core`).

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor(frontend): route state.py through api_client; drop ocd_core shims (Phase 4 Task 5)"
```

---

## Task 6: Split the UI monolith into components

Mechanical extraction of `legacy_frontend/legacy_frontend.py` (1295 lines) into focused modules under `legacy_frontend/components/`. Boundaries are from the verified inventory. `legacy_frontend.py` keeps **only** module-level design tokens, the `app = rx.App(...)`, and the `app.add_page(...)` routing.

**Files (create under `legacy_frontend/components/`):**
- `__init__.py` (empty)
- `theme.py` — design tokens `BORDER`, `CARD_BG`, `PAGE_BG` (lines 10-12)
- `sidebar.py` — `_tab, top_tabs, nav_item, sidebar_recent, user_footer, sidebar` (18-111)
- `project_grid.py` — `project_card, new_project_dialog, dashboard, chat_row, chats_dashboard` (117-270)
- `settings.py` — `_setting_row, customize_page` (276-321)
- `artifact_viewer.py` — `code_page, artifact_card, artifacts_page, add_connector_dialog, connector_row, connectors_page` (327-535)
- `workspace_panels.py` — `panel_header, memory_panel, instructions_panel, file_row, files_panel, conversation_row, recent_tasks, workspace, cowork_page` (541-643, 1184-1252, 410-425)
- `chat_panel.py` — `_user_bubble, _final_bubble, _tool_card, _table_block, _error_bubble, _thinking_block, _source_row, _sources_block, render_message, thinking_indicator` (646-847)
- `composer.py` — `_move_target_item, _skill_item, _builtin_tool_item, _plugin_item, _connector_item, _mcp_item, plus_menu, _model_menu_item, _effort_menu_item, model_pill, _mode_chip, github_dialog, attach_dialog, mcp_add_dialog, composer, workspace_composer` (853-1185)
- `conversation.py` — `rename_dialog, move_target_row, change_project_dialog, conversation_menu, conversation_page` (1258-1377)

**Shared imports each component module needs:** `import reflex as rx`, `from ..state import AppState`, and `from .theme import BORDER, CARD_BG, PAGE_BG` (only where used).

**Cross-module references (must import, not redefine):**
- `sidebar()` is used by `dashboard`, `chats_dashboard`, `workspace`, `cowork_page`, `conversation_page`, `customize_page`, `code_page`, `artifacts_page`, `connectors_page` → those modules do `from .sidebar import sidebar`.
- `composer()` + `workspace_composer()` are used by `workspace`/`cowork_page` and `conversation_page` → `from .composer import composer, workspace_composer`.
- `render_message()` is used by `conversation_page` → `from .chat_panel import render_message`.
- `panel_header()` is used within `workspace_panels.py` (local — no cross-import).

- [ ] **Step 1: Create `theme.py` and move the tokens**

Create `legacy_frontend/components/__init__.py` (empty) and `legacy_frontend/components/theme.py`:
```python
BORDER = "1px solid var(--gray-4)"
CARD_BG = "var(--color-background)"
PAGE_BG = "var(--gray-1)"
```
(Copy the exact values from the current `legacy_frontend.py` lines 10-12.)

- [ ] **Step 2: Extract one module at a time**

For each component module above, in this order (leaves first, shell last): `theme → sidebar → chat_panel → composer → project_grid → artifact_viewer → workspace_panels → settings → conversation`. For each module:
  1. `git mv`-style cut the listed functions (by line range) from `legacy_frontend.py` into the new file.
  2. Add the module header imports (`reflex`, `..state.AppState`, `.theme.*`, and any cross-module component imports listed above).
  3. After each extraction, run the compile check (Step 4) before moving to the next module — fail fast on a missing import.

- [ ] **Step 3: Reduce `legacy_frontend.py` to the shell**

`legacy_frontend/legacy_frontend.py` keeps only:
```python
import reflex as rx
from .state import AppState
from .auth import AuthState, login_page
from .components.project_grid import dashboard, chats_dashboard
from .components.workspace_panels import workspace, cowork_page
from .components.artifact_viewer import code_page, artifacts_page, connectors_page
from .components.settings import customize_page
from .components.conversation import conversation_page

app = rx.App(stylesheet=[...])   # keep the existing stylesheet list verbatim
app.add_page(...)                # keep all 9 add_page calls verbatim (lines 1389-1417)
```
(Keep the exact `rx.App(...)` args and every `add_page` call as they are today; only the component functions now come from imports.)

- [ ] **Step 4: Compile check**

Run:
```bash
cd frontend && REFLEX_USE_NPM=true ../venv312/Scripts/python.exe -c "import legacy_frontend.legacy_frontend"
```
Expected: clean import, no `NameError`/`ImportError`.

- [ ] **Step 5: Frontend tests still green**

Run: `cd frontend && ../venv312/Scripts/python.exe -m pytest tests -q`
Expected: PASS (11).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(frontend): split UI monolith into components/ (Phase 4 Task 6)"
```

---

## Task 7: CORS whitelist + startup health ping

**Files:**
- Modify: `backend/app/main.py`
- Modify: `legacy_frontend/state.py`
- Test: `backend/tests/test_cors.py`

- [ ] **Step 1: Write the failing CORS test**

Create `backend/tests/test_cors.py`:
```python
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_cors_allows_known_origin():
    r = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_rejects_unknown_origin():
    r = client.get("/health", headers={"Origin": "http://evil.example"})
    assert r.headers.get("access-control-allow-origin") != "http://evil.example"
```

- [ ] **Step 2: Run to verify failure**

Run: `venv312/Scripts/python.exe -m pytest backend/tests/test_cors.py -q`
Expected: FAIL — current `allow_origins=["*"]` echoes any origin.

- [ ] **Step 3: Tighten CORS**

In `backend/app/main.py`, replace the `CORSMiddleware` config:
```python
import os

_origins = os.environ.get("OCD_CORS_ORIGINS",
                          "http://localhost:3000,http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- [ ] **Step 4: Run to verify pass**

Run: `venv312/Scripts/python.exe -m pytest backend/tests/test_cors.py -q`
Expected: PASS.

- [ ] **Step 5: Add the frontend startup health ping**

In `legacy_frontend/state.py`, add a state field `backend_ok: bool = True` and `backend_error: str = ""`, and an `on_load` handler used by the index page:
```python
async def check_backend(self):
    try:
        await api_client.health()
        self.backend_ok = True
        self.backend_error = ""
    except Exception as e:
        self.backend_ok = False
        self.backend_error = f"Backend unreachable at {api_client._BASE}: {e}"
```
Wire it as the index page's `on_load` in `legacy_frontend.py` (`app.add_page(..., on_load=AppState.check_backend)` for the dashboard route), and render a banner when `~AppState.backend_ok` in the sidebar/shell.

- [ ] **Step 6: Compile check + commit**

Run: `cd frontend && REFLEX_USE_NPM=true ../venv312/Scripts/python.exe -c "import legacy_frontend.legacy_frontend"`
Expected: clean import.
```bash
git add -A
git commit -m "feat: CORS whitelist + frontend backend health ping (Phase 4 Task 7)"
```

---

## Task 8: End-to-end run (manual, user environment)

Not automatable here (needs live Postgres + GLM + BigQuery). The user runs this on their machine.

- [ ] **Step 1: Start backend** — `uvicorn backend.app.main:app --port 8000` (with Postgres up + `.env` creds).
- [ ] **Step 2: Start frontend** — `cd frontend && REFLEX_USE_NPM=true reflex run` (set `OCD_API_URL=http://localhost:8000` if not default).
- [ ] **Step 3: Verify** — open the app, create/open a project, send one message; confirm the transcript streams thinking → tool cards → table → answer (the real SSE vocab) and the conversation persists (reload shows it). Confirm the dashboard cards, file upload, SQL console, and connector/MCP toggles work against the live backend.
- [ ] **Step 4: Report** any deviation; fix on this branch before finishing.

---

## Self-Review Notes (author)

- **Spec coverage:** api_client (§5) → Task 1; SSE real-vocab (§3) → Task 1 Step 5 `run_agent_stream` + tests; six REST gaps (§6) → Task 2; local formatters (§6) → Task 3; move (§10) → Task 4; decouple (§7) → Task 5; UI split (§8) → Task 6 (**expanded** from the spec's 4 files to the 8 verified component boundaries — recorded as an intentional refinement); CORS + ping (§9) → Task 7; e2e (§11) → Task 8. All spec sections covered.
- **Type consistency:** `import_github_repo` returns `{chunks, message}` everywhere (client + route + state call site). `get_project_memory` returns `tuple[str, str]` (client) matching the route's `{content, updated_rel}`. `run_agent_stream` yields the same dict keys `state.py` already reads.
- **No placeholders:** the only deliberately deferred literals are the two formatter bodies in Task 3 (must be copied verbatim from the named source lines — copying existing code, not inventing) and the verbatim `rx.App`/`add_page` block in Task 6 (preserve as-is). Both name the exact source.
