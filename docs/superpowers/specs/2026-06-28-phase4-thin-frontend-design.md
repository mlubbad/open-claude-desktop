# Phase 4 — Thin the Reflex Frontend (design)

**Date:** 2026-06-28
**Status:** Approved (design); implementation pending plan
**Predecessors:** Phase 1 (consolidate core), Phase 2 (Postgres), Phase 3 (FastAPI + SSE) — all merged to `main`.

## 1. Goal

Turn the Reflex app into a **thin HTTP/SSE client**. After Phase 4 the frontend imports
**zero `ocd_core`** code: every domain operation goes over the network to the FastAPI
backend built in Phase 3. The frontend keeps only presentation, local UI state, and a
typed API client.

This resolves the architecture audit's "frontend reaches into backend internals" finding
and makes the two services independently runnable and deployable.

### Non-goals
- Retiring Chainlit (`app.py`) — that is Phase 5.
- The `runtime/` layout, `backend/content/`, `.claude/` config layer, CI matrix — Phase 6.
- Any change to agent behavior, prompts, or the BigQuery policy.

## 2. Current state (ground truth)

The frontend package is `legacy_frontend/`:

| file | lines | role |
|---|---|---|
| `legacy_frontend.py` | 1295 | UI monolith (all `rx.component` views in one module) |
| `state.py` | 933 | Reflex `AppState`; calls `core.*` / `agent.*` / `integrations.*` directly |
| `auth.py` | 117 | `AuthState` + login page (crypto already from `ocd_core.auth`) |
| `core.py` | 94 | re-export shim → `ocd_core.*` |
| `agent.py` | 8 | re-export shim → `ocd_core.agent` |
| `integrations.py` | 7 | re-export shim → `ocd_core.integrations` |

`state.py` couples to the backend through `from . import core / agent / integrations`
(the shims). There are ~40 distinct call sites. The agent turn is consumed at
[state.py:947](../../../legacy_frontend/state.py) as
`async for ev in agent.run_turn(...)` and rendered by a ~50-line event switch
([state.py:958-1008](../../../legacy_frontend/state.py)).

## 3. The SSE contract (the one correction to the original plan)

The original Phase-4 sketch assumed the agent stream emits `thinking` / `tool` / `table` /
`final` events with `{data: {thought}}` / `{data: {text}}` wrappers. **That contract does
not exist.** The Phase-3 backend serializes every event as:

```python
# backend/app/sse.py
def format_event(ev: dict) -> ServerSentEvent:
    return ServerSentEvent(event=ev.get("type", "message"), data=json.dumps(ev, default=str))
```

So each SSE frame is `event:` = the event `type`, `data:` = **the entire event dict** as
JSON. The real event vocabulary (what `state.py` already renders) is:

| `type` | payload keys |
|---|---|
| `think_open` | `phase` |
| `think_close` | `elapsed` |
| `delta` | `scope` (`answer`\|`think`), `text` — **the answer streams here; there is no `final` event** |
| `answer_open` | — |
| `answer_to_think` | `phase`, `elapsed` |
| `tool` | `id`, `name`, `icon`, `label_running`, `label_done`, `input` |
| `tool_result` | `id`, `summary` |
| `tool_error` | `id`, `text` |
| `table` | `total`, `bytes`, `columns`, `rows` |
| `sources` | `items` |
| `error` | `text` |

Plus two stream-control frames the backend appends in
[routes/agent.py](../../../backend/app/routes/agent.py): a terminal `done` frame on
normal completion, and an `error` frame if `run_turn` raises.

**Decision (approved): preserve the real vocab end-to-end.** `api_client.run_agent_stream`
parses each frame's `data` back into the exact dict the backend emitted and yields it
unchanged. The existing `_run_agent` renderer is reused **verbatim** — the only change is
swapping the event source from `agent.run_turn(...)` to `api_client.run_agent_stream(...)`.
No translation layer, no invented `final` event, nothing lost.

## 4. Architecture after Phase 4

```
frontend/                         backend/  (unchanged in this phase)
  legacy_frontend/
    api_client.py   ──HTTP/SSE──►  app/  (FastAPI)  ──►  ocd_core/
    state.py        (no ocd_core import)
    auth.py
    components/
      sidebar.py
      chat_panel.py
      project_grid.py
      artifact_viewer.py
    legacy_frontend.py    (page assembly only)
  rxconfig.py
  assets/
  requirements.txt   (reflex + httpx + httpx-sse only — no ocd_core)
```

Data flow: a Reflex event handler calls an `await api_client.<op>(...)`; the client adds
`Authorization: Bearer <token>` when a token is set, hits the FastAPI route, and returns the
parsed JSON. The agent turn is an async generator yielding event dicts straight into the
unchanged renderer.

## 5. The API client

`legacy_frontend/api_client.py` — a typed async client over `httpx.AsyncClient`.

- **Base URL** from env `OCD_API_URL`, default `http://localhost:8000`.
- **Auth**: a module-level token (set by `login`); attached as a Bearer header on every
  request when present. When the backend has auth disabled, requests are anonymous and the
  header is simply omitted — matching `deps.current_user`'s anonymous path.
- **Strict typing**: every function has explicit parameter and return type hints; bodies are
  built as typed dicts matching the Pydantic request models in
  [backend/app/schemas.py](../../../backend/app/schemas.py).
- **Errors**: non-2xx raises `ApiError(status, detail)`; callers in `state.py` surface it as
  a UI error message (same UX as today's `try/except`).

### 5.1 REST surface (maps every retained `state.py` call)

| api_client function | method + path | replaces |
|---|---|---|
| `login(username, password) -> str` | POST `/auth/login` | (new — enables Bearer) |
| `list_projects() -> list[dict]` | GET `/projects` | `core.list_projects` |
| `list_project_cards() -> list[dict]` | GET `/projects?view=card` † | `core.project_card_view` |
| `create_project(name) -> dict` | POST `/projects` | `core.create_project` |
| `get_project(pid) -> dict` | GET `/projects/{pid}` | `core.get_project` |
| `delete_project(pid) -> bool` | DELETE `/projects/{pid}` | `core.delete_project` |
| `get_project_instructions(pid) -> str` | GET `/projects/{pid}/instructions` | `core.get_project_instructions` |
| `save_project_instructions(pid, text)` | PUT `/projects/{pid}/instructions` | `core.save_project_instructions` |
| `get_project_memory(pid) -> tuple[str,str]` | GET `/projects/{pid}/memory` | `core.get_project_memory` |
| `project_capacity(pid) -> dict` | GET `/projects/{pid}/capacity` | `core.project_capacity` |
| `list_conversations(pid) -> list[dict]` | GET `/projects/{pid}/conversations` | `core.list_conversations` |
| `create_conversation(pid, first) -> dict` | POST `/projects/{pid}/conversations` | `core.create_conversation` |
| `get_conversation(pid, cid) -> dict` | GET `/projects/{pid}/conversations/{cid}` | `core.get_conversation` |
| `save_conversation(pid, cid, msgs, title) -> dict` | PUT `/projects/{pid}/conversations/{cid}` | `core.save_conversation` |
| `set_conversation_title(pid, cid, title)` | PATCH `/projects/{pid}/conversations/{cid}` | `core.set_conversation_title` |
| `set_conversation_pinned(pid, cid, pinned)` | PATCH `/projects/{pid}/conversations/{cid}` | `core.set_conversation_pinned` |
| `move_conversation(pid, cid, dst) -> bool` | POST `/projects/{pid}/conversations/{cid}/move` | `core.move_conversation` |
| `delete_conversation(pid, cid)` | DELETE `/projects/{pid}/conversations/{cid}` | `core.delete_conversation` |
| `list_all_conversations(limit=200) -> list[dict]` | GET `/conversations` | `core.list_all_conversations` |
| `list_project_files(pid) -> list[dict]` | GET `/projects/{pid}/files` | `core.list_project_files` |
| `upload_file(pid, name, bytes) -> dict` | POST `/projects/{pid}/files` (multipart) | `core.save_uploaded_file` + `core.ingest_file_to_kb` |
| `get_settings() -> dict` | GET `/settings` | `core.get_settings` |
| `save_settings(patch) -> dict` | PUT `/settings` | `core.save_settings` |
| `list_plugins() -> list[dict]` | GET `/plugins` | `integrations.list_plugins` |
| `list_skills() -> list[dict]` | GET `/skills` | `integrations.list_skills` |
| `list_connectors() -> list[dict]` | GET `/connectors` | `integrations.list_connectors` |
| `add_connector(...) -> dict` | POST `/connectors` | `integrations.add_connector` |
| `remove_connector(cid)` | DELETE `/connectors/{cid}` | `integrations.remove_connector` |
| `test_connector(cid) -> str` | POST `/connectors/{cid}/test` | `integrations.test_connector` |
| `list_mcp_servers() -> list[dict]` | GET `/mcp-servers` | `integrations.list_mcp_servers` |
| `add_mcp_server(name, cmd, args) -> dict` | POST `/mcp-servers` | `integrations.add_mcp_server` |
| `remove_mcp_server(sid)` | DELETE `/mcp-servers/{sid}` | `integrations.remove_mcp_server` |
| `search_schema(q, project) -> str` | GET `/schema/search` | (schema panel) |
| `run_agent_stream(req) -> AsyncIterator[dict]` | POST `/agent/turn` (SSE) | `agent.run_turn` |

† see §6 for the `?view=card` endpoint addition.

### 5.2 The SSE method

```python
async def run_agent_stream(req: dict) -> AsyncIterator[dict]:
    async with httpx.AsyncClient(base_url=BASE, timeout=None) as client:
        async with aconnect_sse(client, "POST", "/agent/turn",
                                json=req, headers=_auth_headers()) as es:
            async for sse in es.aiter_sse():
                ev = json.loads(sse.data)
                if ev.get("type") == "done":
                    return
                yield ev
```

`req` is the `AgentTurnRequest` shape: `{project_id, goal, history, model, effort, options,
enabled_plugins, enabled_connectors, enabled_mcp}`. Because the backend resolves the active
skill (`commands.resolve_skill`) and assembles `extra_tools` server-side, the frontend no
longer computes them — it just forwards the enabled-* id lists.

## 6. REST surface gaps to close

Six retained `state.py` calls have **no** Phase-3 endpoint. The frontend must not re-import
`ocd_core`, so each is resolved as follows:

| call | resolution |
|---|---|
| `core.execute_sql(sql, project)` (SQL panel) | **Add** POST `/sql/execute` `{sql, project?}` → `bigquery.execute_sql` |
| `core.list_all_files(limit)` | **Add** GET `/files?limit=` → `knowledge.list_all_files` |
| `core.generate_conversation_title(first)` | **Add** POST `/conversations/title` `{first_message}` → `conversations.generate_conversation_title` |
| `integrations.import_github_repo(url, pid)` | **Add** POST `/connectors/github` `{repo_url, project_id}` → returns `{chunks, message}` |
| `integrations.add_demo_mcp_server()` | **Add** POST `/mcp-servers/demo` → `integrations.add_demo_mcp_server` |
| `core.project_card_view(p)` | **Add** `?view=card` to GET `/projects` (server applies `project_card_view` to each row) |

Two calls are **pure formatters** with no I/O → become tiny local helpers in the frontend
(no network, no `ocd_core`):

- `core.fmt_bytes(n)` → `legacy_frontend/format.py::fmt_bytes`
- `agent._strip_answer_label(text)` → `legacy_frontend/format.py::strip_answer_label`

Three calls **disappear** — the backend already does this work inside `/agent/turn`:

- `integrations.matching_skill`, `integrations.get_skill` (skill auto-trigger → `commands.resolve_skill`)
- `integrations.agent_tools` (tool assembly → server-side `extra_tools`)

All six new endpoints are thin wrappers consistent with the existing 40-op surface and ship
with the same `current_user` dependency. They are added in the api_client task so Task 1's
tests can target the full contract.

## 7. Decoupling `state.py`

- Replace `from . import core / agent / integrations` with `from . import api_client` (and
  `from . import format` for the two local helpers).
- Every call site becomes `await api_client.<op>(...)`. State methods that were synchronous
  but now perform network I/O become `async` event handlers (Reflex supports this).
- The agent loop swaps its source only:
  `async for ev in api_client.run_agent_stream(self._build_turn_request(goal, history, pid)):`
  — the event switch below it is unchanged.
- `_build_turn_request` assembles the `AgentTurnRequest` dict from existing state fields
  (`self.model`, `self.effort`, the `*_on` toggles, `enabled_plugins/connectors/mcp`).
- The re-export shims (`core.py`, `agent.py`, `integrations.py`) are deleted once no frontend
  module imports them.

## 8. UI split

`legacy_frontend.py` (1295 lines) splits into `legacy_frontend/components/`:

- `sidebar.py` — project/conversation nav + global controls
- `chat_panel.py` — transcript renderer (messages, tool cards, thinking, tables, sources)
- `project_grid.py` — dashboard project cards + search
- `artifact_viewer.py` — SQL/table/code artifact surfaces

`legacy_frontend.py` keeps page assembly and routing only: imports the components and composes the
pages. No behavior change — this is a mechanical extraction guided by the existing component
boundaries. `AppState` stays in `state.py`; components reference it as today.

## 9. CORS + startup ping

- Tighten `backend/app/main.py` CORS from `allow_origins=["*"]` to an explicit list:
  `http://localhost:3000`, `http://localhost:5173` (Reflex dev + Vite), overridable via
  `OCD_CORS_ORIGINS` (comma-separated).
- On frontend startup, `AppState` pings GET `/health`; on failure it sets a visible
  "backend unreachable at `{OCD_API_URL}`" banner instead of failing opaquely on first call.

## 10. Move to `frontend/`

`legacy_frontend/` → `frontend/`, flattening the double-nest so the Reflex package lives at
`legacy_frontend/`. Moves `rxconfig.py`, `assets/`, `requirements.txt` (rewritten to
`reflex`, `httpx`, `httpx-sse` — **no** `ocd_core`/editable backend install). `git mv` to
preserve history. The `.web/` build dir is not moved (gitignored, regenerated by `reflex`).

## 11. Testing strategy

- **Task 1 (api_client) — hermetic, the TDD core.** `respx` mocks the httpx transport; no
  live backend. Tests assert:
  - `login` posts credentials, returns the token, and the token is attached as a Bearer
    header on a subsequent call.
  - REST helpers issue the right method+path+body and parse the response shape
    (e.g. `list_project_cards` → card dicts; `get_project_memory` → `(content, updated_rel)`).
  - `run_agent_stream` parses the **real** vocab: a mocked SSE body of
    `think_open` → `delta(scope=think)` → `tool` → `tool_result` → `table` →
    `delta(scope=answer)` → `done` yields exactly those event dicts (minus `done`) in order,
    and terminates on `done`.
  - An `error` frame is yielded through (the renderer handles it); a non-2xx REST response
    raises `ApiError`.
  - New endpoints (`/sql/execute`, `/files`, `/conversations/title`, `/connectors/github`,
    `/mcp-servers/demo`, `/projects?view=card`) get a backend route test each, mocking the
    `ocd_core` function so no live GLM/BigQuery is touched.
- **Task 3+** — `state.py` and the UI split are validated by `reflex` compiling without
  error plus a smoke import test; Reflex view code is not unit-tested (consistent with the
  existing repo).
- **Task 6 (e2e)** — manual, in the user's environment (live GLM/BigQuery): `uvicorn
  backend.app.main:app --port 8000` + `reflex run`, one real agent turn end to end.

## 12. Task order (dependency-forced)

1. **api_client + new endpoints** (TDD; the contract everything else builds on)
2. **Move** `legacy_frontend/` → `frontend/`
3. **Decouple** `state.py` → route through `api_client`; delete shims
4. **Split** the UI monolith into `components/`
5. **CORS** whitelist + startup health ping
6. **e2e** run (manual, user env)

## 13. Risks

- **Sync→async call sites**: converting `state.py` methods to async could expose ordering
  assumptions. Mitigation: convert per-method, keep the renderer untouched, lean on Reflex's
  async event-handler support.
- **Auth-disabled default**: most dev runs have auth off; the client must work fully
  anonymous (no token) — covered by a respx test with no Bearer header.
- **Multipart upload**: `upload_file` must send `multipart/form-data` matching FastAPI's
  `UploadFile`; covered by a respx assertion on the content type.
