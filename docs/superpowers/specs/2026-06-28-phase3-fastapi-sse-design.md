# Design: Phase 3 — FastAPI Service + SSE Agent Stream

> **Date:** 2026-06-28 · **Status:** Draft for review
> **Parent:** `docs/superpowers/specs/2026-06-27-two-service-refactor-design.md` (§3, §4, §8). Phase 3 of 6.

## 1. Context

Phases 1–2 consolidated all domain logic into `backend/ocd_core/` and moved
projects/conversations to Postgres. The Reflex app still calls `ocd_core`
**in-process**. Phase 3 builds the **FastAPI backend service** over `ocd_core`,
turning the in-process backend into a real network service: REST for CRUD +
**SSE for the streaming agent turn**. This phase is **purely additive** — the
Reflex app and `ocd_core` are unchanged; Phase 4 rewires the frontend to call
this service over HTTP.

Key facts grounding the design:
- `agent.run_turn(...)` is an async generator yielding typed event dicts. The
  **real** vocabulary (verified): `think_open`, `think_close`, `answer_open`,
  `delta` (scope `answer`|`think`), `answer_to_think`, `tool`, `tool_result`,
  `tool_error`, `table`, `sources`, `error`. There is **no** single `final` event.
- `state.py` invokes it as `agent.run_turn(goal, history, project_id, model,
  project_instructions, effort=…, web_search=…, skill_instructions=…, research/
  web_fetch/code_exec/bash/text_editor/memory flags, extra_tools=…)` and consumes
  it with `async for ev in …`.
- `bigquery.execute_sql` **already enforces** the per-project allowlist (substring
  match) + banned aliases + read-only + cost cap. It does **not** rate-limit
  (it doesn't know the user).
- Auth crypto (`make_token`/`verify_token`/`credentials_ok`) currently lives in
  `legacy_frontend/auth.py` (Reflex-coupled module) — not yet in `ocd_core`.

## 2. Goals & non-goals

### Goals
1. A runnable **FastAPI service** (`uvicorn backend.app.main:app`) exposing the
   complete surface the Reflex frontend consumes.
2. **`POST /agent/turn` → SSE**: stream `run_turn`'s events to the client.
3. **Complete REST surface**: projects, conversations, knowledge, schema,
   integrations, settings, auth, health — mirroring `ocd_core`.
4. **Extract `ocd_core/auth.py`** (the HMAC crypto) so the backend verifies tokens
   without importing the frontend.
5. **Wire the salvaged guards at the boundary**: per-user **rate limiting** +
   **audit** at `/agent/turn`; **DRY + harden the allowlist** to a parsed
   `referenced_tables` check.
6. Tests with **no external calls** (FastAPI `TestClient`; mocked BigQuery + GLM;
   a fake `run_turn` generator for SSE).

### Non-goals (later phases / YAGNI)
- **No frontend rewire** (Phase 4) — `state.py` keeps using `ocd_core` in-process.
- **No async DB** — `ocd_core` stays sync; sync routes run in FastAPI's threadpool.
- No deployment/Dockerfile/CI changes (Phase 6) beyond running uvicorn locally.
- No new agent features — the agent logic is reused as-is.
- No multi-user RBAC beyond the existing optional single-user auth gate.

## 3. Locked decisions

| Decision | Choice |
|---|---|
| API scope | **Complete surface** (agent SSE + all REST the frontend uses) |
| Guards | **Wire in now**: per-user rate-limit + audit at `/agent/turn`; allowlist hardened (below) |
| Persistence on turn | **Stream-only** SSE; conversation saved via a separate REST call |
| Auth crypto | **Extract to `ocd_core/auth.py`**; optional Bearer dependency |
| Concurrency | **Sync `def` routes** (threadpooled); the agent route is `async` |
| SSE transport | `sse-starlette` `EventSourceResponse` |
| **Allowlist hardening** | Replace the substring check with a **parsed `referenced_tables`** check (from the dry-run), so commented/string table names can't bypass it |

## 4. Architecture

```
backend/
├─ ocd_core/
│  └─ auth.py            # NEW: extracted HMAC crypto (make_token/verify_token/credentials_ok)
└─ app/                  # NEW: FastAPI service over ocd_core
   ├─ __init__.py
   ├─ main.py            # app, router registration, optional-auth, lifespan, CORS
   ├─ deps.py            # current_user dependency (verify Bearer; optional)
   ├─ schemas.py         # Pydantic request/response models
   ├─ sse.py             # run_turn event dict → SSE data line
   └─ routes/
      ├─ agent.py        # POST /agent/turn (SSE)
      ├─ projects.py · conversations.py · knowledge.py · schema.py
      ├─ integrations.py · settings.py · auth.py · health.py
```

`ocd_core` is unchanged except: (a) the new `auth.py`; (b) `bigquery.execute_sql`
+ `sql_guard` updated for the parsed-allowlist hardening (§7). The Reflex
`legacy_frontend/auth.py` keeps `AuthState`/`login_page` and imports the
crypto from `ocd_core.auth` (a one-line repoint; verified it still runs).

### Concurrency model
- REST routes are plain `def` → FastAPI runs them in a worker threadpool, so the
  blocking `ocd_core` calls (DB commits, ChromaDB, file I/O) don't block the loop.
- `/agent/turn` is `async def` and iterates the async `run_turn` generator directly,
  yielding SSE events as they arrive.

### Auth (optional, parity with current)
- `ocd_core/auth.py`: `make_token(user)`, `verify_token(token)`, `credentials_ok(u,p)`
  (constant-time `hmac.compare_digest`), reading `APP_USERNAME`/`APP_PASSWORD`/
  `APP_AUTH_SECRET` (with back-compat `CHAINLIT_AUTH_SECRET`).
- `deps.current_user`: if creds are **unset** → auth disabled (returns an
  anonymous user); if set → require a valid `Authorization: Bearer <token>` (401
  otherwise). `POST /auth/login` validates creds and returns a token.

## 5. The agent SSE endpoint (centerpiece)

`POST /agent/turn` — body:
```
{ project_id: str|null, goal: str, history: [{role,content,kind}],
  model: str, effort: "Low"|"Medium"|"High"|"Max",
  options: { web_search, research, web_fetch, code_exec, bash, text_editor, memory },
  enabled_plugins: [str], enabled_connectors: [str], enabled_mcp: [str] }
```
Route logic:
1. `current_user` (auth dependency).
2. **Rate limit:** `observability.check_rate_limit(user_id)` → **429** if blocked
   (`audit({"event":"rate_limited", ...})`).
3. Resolve `project_instructions` (`projects.get_project_instructions`) and
   `skill_instructions` (`commands.resolve_skill`/`skills`); assemble
   `extra_tools = integrations.agent_tools(enabled_plugins, enabled_connectors, enabled_mcp)`.
4. `audit({"event":"agent_turn", "user":…, "project":…, "goal":goal[:200]})`.
5. Return `EventSourceResponse` streaming each `run_turn(...)` event dict as one
   SSE message: `event: <type>` + `data: <json of the event>`. A terminal
   `event: done` closes the stream. `error` events are forwarded as-is.
6. **No DB write** here — the client persists via `POST /projects/{pid}/conversations/{cid}`.

`sse.py` provides `format_event(ev: dict) -> ServerSentEvent` (type from `ev["type"]`,
data = `json.dumps(ev)`), keeping the route thin and unit-testable.

## 6. REST surface + schemas

All under optional auth. Sync `def` routes calling `ocd_core`. Pydantic models in
`schemas.py`. Shapes mirror `ocd_core`'s return dicts (datetimes already ISO strings).

```
Auth:          POST /auth/login {username,password} -> {token}
Projects:      GET /projects · POST /projects {name} · GET /projects/{pid}
               DELETE /projects/{pid}
               GET/PUT /projects/{pid}/instructions · /memory · /allowlist
Conversations: GET /projects/{pid}/conversations · POST .../conversations {first_message}
               GET /projects/{pid}/conversations/{cid}
               PUT /projects/{pid}/conversations/{cid} {messages,title}   # save (persistence)
               PATCH .../{cid} {title?,pinned?} · DELETE .../{cid}
               POST .../{cid}/move {dst_project_id}
               GET /conversations  (list_all, ?limit=)
Knowledge:     POST /projects/{pid}/files (multipart upload → ingest)
               GET /projects/{pid}/files · GET /projects/{pid}/capacity
Schema:        GET /schema/search?q=&project= · POST /schema/rebuild · GET /schema/status
Integrations:  GET/POST/DELETE /connectors · POST /connectors/{id}/test
               GET/POST/DELETE /mcp-servers · GET /mcp-servers/{id}/tools
               GET /plugins · GET /skills
Settings:      GET /settings · PUT /settings
Health:        GET /healthz   (process up) · GET /readyz (DB reachable)
```
Representative Pydantic models (illustrative — exact in the plan):
`ProjectCreate{name}`, `ProjectMeta{id,name,created_at}`, `InstructionsBody{content}`,
`AllowlistBody{tables:[str]}`, `ConversationCreate{first_message}`,
`ConversationSave{messages:[Message],title?}`, `Message{role,content,kind}`,
`ConversationPatch{title?,pinned?}`, `MoveBody{dst_project_id}`,
`AgentTurnRequest{…§5…}`, `SettingsBody{model?,effort?,theme?}`, `LoginRequest{username,password}`, `TokenResponse{token}`.

## 7. Guards wiring (the security work)

1. **Rate limiting** (genuine addition — `execute_sql` can't do it): enforced once
   per turn at `/agent/turn` via `observability.check_rate_limit(user_id)`. 429 on block.
2. **Audit** (compliance posture): `observability.audit(...)` at the turn boundary
   (turn start, rate-limit blocks) — append-only JSONL, no secrets.
3. **Allowlist hardening + DRY** (in `ocd_core`, behavior-improving):
   - Add `sql_guard.tables_off_allowlist(referenced_tables: list[str], allowlist: list[str]) -> bool`
     — returns True if a non-empty allowlist is in force and **any referenced table
     is not in the allowlist** (parsed-reference semantics, mirroring
     `tables_out_of_scope`). This supersedes the substring `tables_off_allowlist(sql, allowlist)`.
   - In `execute_sql`: move the allowlist check **after** the dry-run; read
     `job.referenced_tables` from the dry-run job (qualified `dataset.table` ids)
     and pass them to the new guard. A commented/string table name no longer bypasses it.
   - **Behavior note (approved):** this is a deliberate hardening — the old check
     was permissive (pass if *any* allowed table appeared anywhere in the text);
     the new check is correct (reject if *any accessed* table is off-allowlist).
     `_dry_run` is extended to also return `referenced_tables`.

## 8. Testing strategy

- **No external calls.** `TestClient(app)`; DB via the SQLite `db` fixture; auth
  toggled by setting/unsetting `APP_USERNAME`/`APP_PASSWORD`.
- **SSE (the key test):** monkeypatch `agent.run_turn` with a **fake async
  generator** yielding a scripted sequence (`think_open`→`delta`(think)→
  `answer_open`→`delta`(answer)→`tool`→`table`→`done`). Assert the endpoint emits
  the matching SSE frames (event types + JSON payloads) in order, and that
  rate-limit/auth gates fire (429/401). No GLM is contacted.
- **execute_sql allowlist hardening:** unit-test `sql_guard.tables_off_allowlist`
  on parsed references (allowed-only passes; an off-allowlist referenced table is
  blocked; the comment-injection case `… -- allowed` is now BLOCKED). Test
  `execute_sql` with a fake dry-run returning `referenced_tables` (no real BigQuery).
- **REST routes:** `TestClient` round-trips for projects/conversations/settings
  CRUD against SQLite; knowledge upload via `TestClient` multipart with a small
  text file; schema search with a mocked Chroma. Each asserts status + body shape.
- **Auth:** login issues a token; protected routes 401 without it (creds set) and
  pass when disabled (creds unset); `ocd_core.auth` crypto unit tests (round-trip,
  expiry, tamper).

## 9. Implementation slices (high-level; detailed TDD plan follows)

1. **Auth extraction** — `ocd_core/auth.py` (crypto, unit-tested); repoint the
   Reflex `auth.py` to import it; both apps still import.
2. **App skeleton + auth + health** — `backend/app/{main,deps,schemas}.py`,
   `routes/{health,auth}.py`; `TestClient` boots; `/healthz`/`/readyz`; `/auth/login`
   + the optional-auth dependency (enabled/disabled tests).
3. **Allowlist hardening** — `_dry_run` returns `referenced_tables`; new parsed
   `sql_guard.tables_off_allowlist`; `execute_sql` reordered to use it; unit tests
   incl. the comment-injection case.
4. **Agent SSE endpoint** — `sse.py` + `routes/agent.py`; rate-limit + audit;
   fake-generator SSE test; 429/401 gates.
5. **REST: projects + conversations + settings** — CRUD routes + schemas; TestClient round-trips.
6. **REST: knowledge + schema + integrations** — uploads, schema search/rebuild, connectors/mcp/plugins/skills; mocked Chroma/BigQuery.

Each slice leaves the suite green and both apps importing; the FastAPI service is
runnable from slice 2 onward (`uvicorn backend.app.main:app`).

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| SSE framing / client disconnects | `sse-starlette` handles framing + disconnect; thin `sse.py`; explicit `done`/`error` events; the unit test asserts the frame sequence |
| Sync routes blocking the loop | plain `def` routes are threadpooled by FastAPI; only `/agent/turn` is async (iterating the async generator) |
| Allowlist semantic change breaks a real query | the hardening is approved; the new check is stricter — tested with allowed-only (pass), off-allowlist (block), and comment-injection (block); the dataset-scope guard already uses the same parsed pattern |
| `referenced_tables` unavailable on some dry-runs | fall back to "block if allowlist in force and no referenced_tables resolved" only when a non-empty allowlist exists; otherwise allow (no allowlist = no restriction) — documented in the guard |
| Auth extraction breaks the Reflex login | extract crypto only; `AuthState`/`login_page` stay in the Reflex module importing from `ocd_core.auth`; verify `import legacy_frontend.legacy_frontend` |
| External calls leaking into tests | all BigQuery/GLM/Chroma mocked; the fake `run_turn` generator; CI-safe (SQLite, no network) |

## 11. Open questions

None blocking. Deferred by design: frontend rewire (Phase 4), async DB / per-request
sessions, deployment + CORS hardening + Dockerfiles + CI (Phase 6), retiring the
Chainlit auth/data layer (Phase 5).
