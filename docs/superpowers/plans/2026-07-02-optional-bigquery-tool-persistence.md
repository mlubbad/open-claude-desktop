# Optional BigQuery Capability + Per-Conversation Tool Persistence — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the frontend package `aj360_app`→`ocd_app`, persist each conversation's tool/capability selection so it survives reconnects, and make BigQuery an optional capability (default OFF) instead of the agent's hard-wired identity.

**Architecture:** Backend adds a `tools` JSON column to `Conversation` (persist/restore the full selection) and makes the BigQuery tools + prompt conditional on an `options.bigquery` flag; the system prompt is composed from a generic base plus a BigQuery block only when enabled. Frontend snapshots/restores the selection around the existing per-turn saves and adds a `bigquery_on` toggle.

**Tech Stack:** Python 3.12, FastAPI, SQLModel/SQLAlchemy + Alembic, Reflex (frontend), pytest / respx.

**Conventions used below:**
- Backend tests that import `from backend.app.main import app` run from the **repo root**; tests that import `from ocd_core …` / `from app …` run from **`backend/`**. Each command below states its cwd.
- `PY` = `venv312/Scripts/python.exe` (from repo root) or `../venv312/Scripts/python.exe` (from `backend/`/`frontend/`).

---

## Task 1: Rename frontend package `aj360_app` → `ocd_app`

Mechanical refactor. The existing frontend test suite is the safety net (no new tests). Do this first so all later frontend paths use `ocd_app`.

**Files:**
- Move: `frontend/aj360_app/` → `frontend/ocd_app/`; `frontend/ocd_app/aj360_app.py` → `frontend/ocd_app/ocd_app.py`
- Modify: `frontend/rxconfig.py`
- Modify (imports): `frontend/tests/test_home.py`, `frontend/tests/test_api_client.py`, `frontend/tests/conftest.py`
- Delete: `frontend/.web/` (Reflex regenerates it for the new app_name)

- [ ] **Step 1: Stop any running frontend, then move the package dir + entry file**

```bash
# From repo root. (Stop the running `reflex run` first — see note at end of task.)
cd frontend
git mv aj360_app ocd_app
git mv ocd_app/aj360_app.py ocd_app/ocd_app.py
```

- [ ] **Step 2: Update `rxconfig.py`** (`app_name` + the reload-path override)

Replace the two `aj360_app` occurrences:

```python
os.environ.setdefault("REFLEX_HOT_RELOAD_OVERRIDE_PATHS", "ocd_app")

config = rx.Config(
    app_name="ocd_app",
```

- [ ] **Step 3: Rewrite absolute `aj360_app.` imports across the package + tests**

Only **absolute** imports need changing (relative `from .state import …` are unaffected by the dir rename). Find them:

```bash
# From repo root
grep -rn "aj360_app" frontend/ocd_app frontend/tests frontend/rxconfig.py
```

Expected remaining hits are all absolute references. Edit each to `ocd_app`:
- `frontend/tests/test_home.py`: `from aj360_app.state import _time_greeting` → `from ocd_app.state import _time_greeting`
- `frontend/tests/test_api_client.py`: `import aj360_app.api_client as api_client` → `import ocd_app.api_client as api_client`
- `frontend/tests/conftest.py`: `import aj360_app.api_client as api_client` → `import ocd_app.api_client as api_client`
- Any `aj360_app.` inside `ocd_app/*.py` (e.g. a self-referential absolute import) → `ocd_app.`

- [ ] **Step 4: Delete the compiled web dir (app_name-specific)**

```bash
# From repo root
rm -rf frontend/.web
```

- [ ] **Step 5: Verify no stray references remain**

```bash
# From repo root — expect NO output
grep -rn "aj360_app" frontend/ocd_app frontend/tests frontend/rxconfig.py
```
Expected: (empty). If anything prints, fix it. Do NOT touch `aj360.*`, `AJ360_*`, or backend files.

- [ ] **Step 6: Run the frontend unit suite (the rename safety net)**

```bash
cd frontend
../venv312/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider
```
Expected: PASS (same count as before the rename, currently 32 passed).

- [ ] **Step 7: Commit**

```bash
# From repo root
git add -A frontend/
git commit -m "refactor(frontend): rename Reflex package aj360_app -> ocd_app"
```

- [ ] **Step 8: Manual compile check (once, after committing)**

```bash
cd frontend
OCD_API_URL=http://localhost:8000 REFLEX_USE_NPM=true ../venv312/Scripts/reflex.exe run --backend-port 8001 --frontend-port 3000
```
Expected: fresh `.web` compile reaches `App running at: http://localhost:3000/` with no errors. Stop it (Ctrl+C) once confirmed; the running-app relaunch is covered by the manual verification at the end.

---

## Task 2: Backend — add `tools` JSON column to `Conversation`

**Files:**
- Modify: `backend/ocd_core/db/models.py` (Conversation model)
- Create: `backend/ocd_core/db/migrations/versions/a1b2c3d4e5f6_add_conversation_tools.py`
- Test: `backend/tests/test_conversation_tools.py`

- [ ] **Step 1: Write the failing test** (model has a `tools` dict field, default empty)

Create `backend/tests/test_conversation_tools.py`:

```python
"""Persist per-conversation tool/capability selection."""
from __future__ import annotations


def test_conversation_model_has_tools_default_empty():
    from ocd_core.db.models import Conversation
    c = Conversation(id="c1", project_id="p", title="T")
    assert c.tools == {}


def test_save_and_get_conversation_roundtrips_tools(db):
    from ocd_core import conversations
    conversations.create_conversation("p", "hi")
    convs = conversations.list_conversations("p")
    cid = convs[0]["id"]
    tools = {"mcp": ["playwright"], "bigquery": True, "web_fetch": True}
    conversations.save_conversation("p", cid, [{"role": "user", "content": "x", "kind": "user"}],
                                    title="T", tools=tools)
    got = conversations.get_conversation("p", cid)
    assert got["tools"] == tools
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd backend
../venv312/Scripts/python.exe -m pytest tests/test_conversation_tools.py -q -p no:cacheprovider
```
Expected: FAIL — `TypeError`/`AttributeError` (no `tools` field) and `save_conversation()` got an unexpected keyword `tools`.

- [ ] **Step 3: Add the model column**

In `backend/ocd_core/db/models.py`, in `class Conversation`, add after the `transcript` line:

```python
    tools: dict = Field(default_factory=dict, sa_column=Column(JSON))
```
(`Column` and `JSON` are already imported for `transcript`.)

- [ ] **Step 4: Add `tools` param to save + include in `_to_dict`**

In `backend/ocd_core/conversations.py`, update `save_conversation` signature and body:

```python
def save_conversation(project_id: str, conv_id: str, messages: list[dict],
                      title: str | None = None, tools: dict | None = None) -> dict:
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
        if tools is not None:
            c.tools = tools
        c.updated_at = utcnow()
        s.add(c)
        return _to_dict(c)
```

In the same file, find `_to_dict(c)` and add `tools` to the returned dict:

```python
        "tools": getattr(c, "tools", {}) or {},
```
(Add this key alongside the existing keys like `pinned`/`messages`.)

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd backend
../venv312/Scripts/python.exe -m pytest tests/test_conversation_tools.py -q -p no:cacheprovider
```
Expected: PASS (2 passed). The `db` fixture uses in-memory SQLite via `init_db`, so the new column is created from the model automatically.

- [ ] **Step 6: Create the Alembic migration** (for Postgres + persistent SQLite)

Create `backend/ocd_core/db/migrations/versions/a1b2c3d4e5f6_add_conversation_tools.py`:

```python
"""add conversation.tools

Revision ID: a1b2c3d4e5f6
Revises: 803915bc18bc
Create Date: 2026-07-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "803915bc18bc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversation", sa.Column("tools", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversation", "tools")
```

- [ ] **Step 7: Commit**

```bash
# From repo root
git add backend/ocd_core/db/models.py backend/ocd_core/conversations.py \
        backend/ocd_core/db/migrations/versions/a1b2c3d4e5f6_add_conversation_tools.py \
        backend/tests/test_conversation_tools.py
git commit -m "feat(backend): persist per-conversation tool selection (Conversation.tools)"
```

---

## Task 3: Backend — pass `tools` through the save route

**Files:**
- Modify: `backend/app/schemas.py` (`ConversationSave`)
- Modify: `backend/app/routes/conversations.py` (PUT handler)
- Test: `backend/tests/test_rest_conversations.py` (add a case)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_rest_conversations.py`:

```python
def test_put_conversation_persists_tools(client):
    client.post("/projects", json={"name": "P"})
    conv = client.post("/projects/p/conversations", json={"first_message": "hi"}).json()
    cid = conv["id"]
    r = client.put(f"/projects/p/conversations/{cid}",
                   json={"messages": [{"role": "user", "content": "x", "kind": "user"}],
                         "title": "T",
                         "tools": {"mcp": ["playwright"], "bigquery": False}})
    assert r.status_code == 200
    got = client.get(f"/projects/p/conversations/{cid}").json()
    assert got["tools"] == {"mcp": ["playwright"], "bigquery": False}
```

- [ ] **Step 2: Run it to verify it fails**

```bash
# From repo ROOT (this file imports `from backend.app.main import app`)
venv312/Scripts/python.exe -m pytest backend/tests/test_rest_conversations.py::test_put_conversation_persists_tools -q -p no:cacheprovider
```
Expected: FAIL — `got["tools"]` is `{}` (the route ignores the field) — `KeyError`/assertion mismatch.

- [ ] **Step 3: Add `tools` to the schema**

In `backend/app/schemas.py`, in `class ConversationSave`:

```python
class ConversationSave(BaseModel):
    # NOT list[Message]: the frontend persists its full rich transcript here (see the
    # 422 fix). `tools` is the per-conversation tool/capability selection snapshot.
    messages: list[dict]
    title: str | None = None
    tools: dict | None = None
```

- [ ] **Step 4: Forward `tools` in the PUT handler**

In `backend/app/routes/conversations.py`, update `save_conv`:

```python
@router.put("/projects/{pid}/conversations/{cid}")
def save_conv(pid: str, cid: str, body: ConversationSave, user: str = Depends(current_user)) -> dict:
    return conversations.save_conversation(pid, cid, body.messages, body.title, body.tools)
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
venv312/Scripts/python.exe -m pytest backend/tests/test_rest_conversations.py -q -p no:cacheprovider
```
Expected: PASS (all cases in the file).

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas.py backend/app/routes/conversations.py backend/tests/test_rest_conversations.py
git commit -m "feat(backend): accept tools snapshot on conversation save route"
```

---

## Task 4: Backend — make BigQuery an optional capability

**Files:**
- Modify: `backend/ocd_core/agent.py` (split prompt, gate tools, `run_turn` param)
- Modify: `backend/app/schemas.py` (`AgentOptions.bigquery`)
- Modify: `backend/app/routes/agent.py` (pass `o.bigquery`)
- Test: `backend/tests/test_agent_bigquery_optional.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_agent_bigquery_optional.py`:

```python
"""BigQuery is an optional capability, not the hard-wired identity."""
from __future__ import annotations

from ocd_core import agent


def test_base_prompt_is_generic_without_bigquery():
    sp = agent._system_prompt(bigquery=False)
    low = sp.lower()
    assert "open claude desktop" in low
    assert "search_schema" not in low            # BigQuery loop absent
    assert "banned aliases" not in low


def test_bigquery_prompt_present_when_enabled():
    sp = agent._system_prompt(bigquery=True)
    assert "search_schema" in sp
    assert "run_sql" in sp
    assert "AJ360" in sp


def test_bigquery_tools_gated(monkeypatch):
    # capture the tools list passed to the LLM without doing real I/O
    captured = {}

    async def fake_stream_llm(llm, model, messages, tools=None, **kw):
        captured["tools"] = tools
        captured["system"] = messages[0]["content"]
        yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", fake_stream_llm)
    monkeypatch.setattr(agent, "get_llm_client", lambda: object())
    monkeypatch.setattr(agent.schema_catalog, "ensure_catalog", lambda: None)

    import asyncio

    async def collect(bigquery):
        captured.clear()
        async for _ in agent.run_turn("hi", [], None, "glm-4-flash",
                                      effort="Low", bigquery=bigquery):
            pass
        names = {t["function"]["name"] for t in (captured["tools"] or [])}
        return names

    off = asyncio.run(collect(False))
    on = asyncio.run(collect(True))
    assert "search_schema" not in off and "run_sql" not in off
    assert "search_schema" in on and "run_sql" in on
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd backend
../venv312/Scripts/python.exe -m pytest tests/test_agent_bigquery_optional.py -q -p no:cacheprovider
```
Expected: FAIL — `_system_prompt()` has no `bigquery` kwarg; base prompt still contains `search_schema`; `run_turn` has no `bigquery` param.

- [ ] **Step 3: Split the system prompt in `agent.py`**

Replace the single `SYSTEM_PROMPT = f"""…"""` block with a generic base + a BigQuery block:

```python
BASE_PROMPT = """You are Open Claude Desktop, a helpful, capable assistant.

Use whatever tools are enabled for this turn — which may include web search / web
fetch, a browser and other MCP connectors, code execution, and file editing — to
accomplish the user's actual request. Do NOT assume every task is a data query; pick
the right tool for what was asked, and if no tool fits, just answer directly.

Before calling tools, say in ONE short sentence what you're about to do and why. After
seeing results, note in ONE short sentence what you learned before the next step. When
you need several INDEPENDENT pieces of information, request those tools together so they
run in parallel. If a tool errors, read it, correct your input, and retry — or explain
why you can't proceed. Never give up silently.

Be terse, evidence-first, American English."""


BIGQUERY_PROMPT = f"""

# BIGQUERY (AJ360) CAPABILITY — ENABLED
You can query the AJ360 (Al Jazeera 360) OTT platform data in BigQuery.
Project: `{config.PROJECT_ID}`  Region: EU. Dialect: BigQuery standard SQL.

For BigQuery data questions, the loop is:
1. Call `search_schema` to get EXACT table and column names AND check the knowledge wiki.
2. Write fully-qualified SQL using the EXACT table names from search_schema.
3. Call `run_sql`. If it returns an error, fix the SQL and retry.
4. When you have data, write the final answer with exact numbers in a Markdown table.

This chat is READ-ONLY: only SELECT runs. Do not attempt INSERT/UPDATE/DELETE/DDL.

Hard rules (AJ360-specific):
- Profile suspicious columns before trusting them.
- DATE vs TIMESTAMP: confirm from schema before comparing.
- Banned aliases: {', '.join(sorted(sql_guard.BANNED_ALIASES))}.
- Device: always `devicetype`, NEVER `device_category`.
- video_completion_rate is broken -> SAFE_DIVIDE workaround.
- Aggregate on series_id, NOT series_title.
- Default window: CURRENT_DATE() - 2.
- GA4 tables are huge: filter by stream_id + short window for UNNEST.
- Search funnels are separate per platform."""
```

Delete the old `SYSTEM_PROMPT` constant.

- [ ] **Step 4: Update `_system_prompt(...)` to compose the base + optional blocks**

```python
def _system_prompt(project_instructions: str = "", skill_instructions: str = "",
                   research: bool = False, memory: bool = False,
                   bigquery: bool = False) -> str:
    sp = BASE_PROMPT
    if bigquery:
        sp += BIGQUERY_PROMPT
    if memory:
        sp += ("\n\n# MEMORY PROTOCOL\n"
               "You have a persistent `memory` tool backed by /memories. At the START of a "
               "task, ALWAYS call `memory` with command=view, path=/memories to recover "
               "relevant prior context. Record durable facts, decisions, and task state "
               "with memory create / str_replace so they survive across conversations.\n")
    if project_instructions.strip():
        sp += ("\n\n# PROJECT-SPECIFIC INSTRUCTIONS\n"
               "You are operating inside a project. Adhere strictly to:\n"
               f"{project_instructions.strip()}\n")
    if skill_instructions.strip():
        sp += ("\n\n# ACTIVE SKILL\n"
               "Follow this skill's guidance for this turn:\n"
               f"{skill_instructions.strip()}\n")
    if research:
        sp += ("\n\n# RESEARCH MODE\n"
               "Use `deep_research` ONCE to gather parallel multi-source findings, then "
               "cross-check the sources and synthesize a structured answer that CITES the "
               "sources you used.\n")
    return sp
```

- [ ] **Step 5: Gate the BigQuery tools + thread the flag through `run_turn`**

In `run_turn`'s signature add `bigquery: bool = False` (e.g. next to `memory: bool = False`).

Change the tool-list assembly. Replace `tools = list(TOOLS)` with:

```python
    tools = list(TOOLS) if bigquery else []
```

Update the `_system_prompt(...)` call inside `run_turn` to pass the flag:

```python
    messages = [{"role": "system",
                 "content": _system_prompt(project_instructions, skill_instructions,
                                           research, memory=memory, bigquery=bigquery)},
                *history, {"role": "user", "content": goal}]
```

(`TOOLS` stays defined as `[search_schema, run_sql]`; it is now included only when `bigquery=True`.)

- [ ] **Step 6: Add `bigquery` to `AgentOptions` and pass it in the route**

In `backend/app/schemas.py`, `class AgentOptions`, add:

```python
    bigquery: bool = False
```

In `backend/app/routes/agent.py`, add `bigquery=o.bigquery` to the `run_turn(...)` call:

```python
            async for ev in agent.run_turn(
                    goal, history, req.project_id, req.model, proj_instr,
                    effort=req.effort, web_search=o.web_search, skill_instructions=skill_instr,
                    research=o.research, extra_tools=extra_tools, web_fetch=o.web_fetch,
                    code_exec=o.code_exec, bash=o.bash, text_editor=o.text_editor,
                    memory=o.memory, bigquery=o.bigquery):
```

- [ ] **Step 7: Run the new tests + the agent SSE test (regression)**

```bash
cd backend
../venv312/Scripts/python.exe -m pytest tests/test_agent_bigquery_optional.py tests/test_agent_sse.py -q -p no:cacheprovider
```
Expected: PASS. If `test_agent_sse.py` assumed BigQuery tools were always present, update it to pass `bigquery=True` (adjust that test, not the production default).

- [ ] **Step 8: Commit**

```bash
git add backend/ocd_core/agent.py backend/app/schemas.py backend/app/routes/agent.py \
        backend/tests/test_agent_bigquery_optional.py
git commit -m "feat(backend): make BigQuery an optional capability (default off) with composed prompt"
```

---

## Task 5: Frontend — persist selection + BigQuery toggle (in `ocd_app`)

**Files:**
- Modify: `frontend/ocd_app/api_client.py` (`save_conversation` sends `tools`)
- Modify: `frontend/ocd_app/state.py` (`bigquery_on`, `toggle_bigquery`, `_current_tools`, `_apply_tools`, `active_modes`, save sites, `load_conversation`, `_build_turn_request`)
- Modify: `frontend/ocd_app/components/composer.py` (BigQuery toggle row)
- Test: `frontend/tests/test_api_client.py`, `frontend/tests/test_tool_persistence.py`

- [ ] **Step 1: Write the failing api_client test**

Append to `frontend/tests/test_api_client.py`:

```python
@respx.mock
async def test_save_conversation_sends_tools():
    route = respx.put("http://test/projects/p1/conversations/c1").mock(
        return_value=httpx.Response(200, json={"id": "c1"}))
    tools = {"mcp": ["playwright"], "bigquery": False}
    await api_client.save_conversation("p1", "c1", [{"role": "user", "content": "x"}],
                                       title="T", tools=tools)
    body = json.loads(route.calls.last.request.content)
    assert body["tools"] == tools
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd frontend
../venv312/Scripts/python.exe -m pytest tests/test_api_client.py::test_save_conversation_sends_tools -q -p no:cacheprovider
```
Expected: FAIL — `save_conversation()` has no `tools` param (`TypeError`).

- [ ] **Step 3: Add `tools` to `api_client.save_conversation`**

In `frontend/ocd_app/api_client.py`, update:

```python
async def save_conversation(pid: str, cid: str, messages: list[dict],
                            title: str | None = None, tools: dict | None = None) -> dict:
    return await _put(f"/projects/{pid}/conversations/{cid}",
                      {"messages": messages, "title": title, "tools": tools})  # type: ignore[return-value]
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd frontend
../venv312/Scripts/python.exe -m pytest tests/test_api_client.py -q -p no:cacheprovider
```
Expected: PASS (all api_client tests).

- [ ] **Step 5: Write the failing state round-trip test**

Create `frontend/tests/test_tool_persistence.py`:

```python
"""AppState snapshots and restores the per-conversation tool/capability selection."""
from __future__ import annotations

from ocd_app.state import AppState


def test_current_tools_snapshot_and_apply_roundtrip():
    inst = AppState.__new__(AppState)  # bare instance; we only exercise the two helpers
    # seed a non-default selection
    inst.enabled_plugins = ["calculator"]
    inst.enabled_connectors = []
    inst.enabled_mcp = ["playwright"]
    inst.web_search_on = True
    inst.research_on = False
    inst.web_fetch_on = False
    inst.code_exec_on = False
    inst.bash_on = False
    inst.text_editor_on = False
    inst.memory_on = True
    inst.active_skill = "hero"
    inst.bigquery_on = True

    snap = AppState._current_tools(inst)
    assert snap["mcp"] == ["playwright"]
    assert snap["bigquery"] is True
    assert snap["skill"] == "hero"

    # apply onto a fresh bare instance and confirm the fields come back
    fresh = AppState.__new__(AppState)
    AppState._apply_tools(fresh, snap)
    assert fresh.enabled_mcp == ["playwright"]
    assert fresh.bigquery_on is True
    assert fresh.web_search_on is True
    assert fresh.memory_on is True
    assert fresh.active_skill == "hero"
```

- [ ] **Step 6: Run to verify it fails**

```bash
cd frontend
../venv312/Scripts/python.exe -m pytest tests/test_tool_persistence.py -q -p no:cacheprovider
```
Expected: FAIL — `AppState` has no `_current_tools`/`_apply_tools` (and no `bigquery_on`).

- [ ] **Step 7: Add `bigquery_on`, toggle, snapshot/apply helpers, and the chip**

In `frontend/ocd_app/state.py`:

(a) Add the field next to the other tool toggles (after `memory_on: bool = False`):

```python
    bigquery_on: bool = False             # optional BigQuery (AJ360) capability, default OFF
```

(b) Add the toggle next to `toggle_memory`:

```python
    def toggle_bigquery(self):
        self.bigquery_on = not self.bigquery_on
```

(c) Add the two helpers (place them near `_build_turn_request`):

```python
    def _current_tools(self) -> dict:
        """Snapshot the full per-conversation tool/capability selection."""
        return {
            "plugins": list(self.enabled_plugins),
            "connectors": list(self.enabled_connectors),
            "mcp": list(self.enabled_mcp),
            "web_search": self.web_search_on,
            "research": self.research_on,
            "web_fetch": self.web_fetch_on,
            "code_exec": self.code_exec_on,
            "bash": self.bash_on,
            "text_editor": self.text_editor_on,
            "memory": self.memory_on,
            "skill": self.active_skill,
            "bigquery": self.bigquery_on,
        }

    def _apply_tools(self, tools: dict) -> None:
        """Restore selection from a saved snapshot; keep defaults for absent keys."""
        if not tools:
            return
        self.enabled_plugins = list(tools.get("plugins", self.enabled_plugins))
        self.enabled_connectors = list(tools.get("connectors", self.enabled_connectors))
        self.enabled_mcp = list(tools.get("mcp", self.enabled_mcp))
        self.web_search_on = bool(tools.get("web_search", self.web_search_on))
        self.research_on = bool(tools.get("research", self.research_on))
        self.web_fetch_on = bool(tools.get("web_fetch", self.web_fetch_on))
        self.code_exec_on = bool(tools.get("code_exec", self.code_exec_on))
        self.bash_on = bool(tools.get("bash", self.bash_on))
        self.text_editor_on = bool(tools.get("text_editor", self.text_editor_on))
        self.memory_on = bool(tools.get("memory", self.memory_on))
        self.active_skill = tools.get("skill", self.active_skill)
        self.bigquery_on = bool(tools.get("bigquery", self.bigquery_on))
```

(d) In `active_modes`, add a chip (before the `active_skill` chip):

```python
        if self.bigquery_on:
            chips.append("BigQuery")
```

- [ ] **Step 8: Persist on save + restore on load + send the flag**

In `frontend/ocd_app/state.py`:

(a) Both `save_conversation(...)` call sites — pass the snapshot. Site 1 (in `send_message`):

```python
        await api_client.save_conversation(self.current_id, self.current_conv_id,
                                           self.messages, self.conv_title or None,
                                           self._current_tools())
```

Site 2 (in `_run_agent`, the post-turn save):

```python
        await api_client.save_conversation(pid, cid, self.messages,
                                           self.conv_title or None, self._current_tools())
```
(Match the exact existing positional args at that site; append `self._current_tools()` as the `tools` arg.)

(b) In `load_conversation`, after `self.messages = self._normalize_messages(...)`, add:

```python
        self._apply_tools(conv.get("tools") or {})
```

(c) In `_build_turn_request`, add `bigquery` to the `options` dict:

```python
                "memory": self.memory_on,
                "bigquery": self.bigquery_on,
```

- [ ] **Step 9: Add the composer toggle row**

In `frontend/ocd_app/components/composer.py`, inside the `plus_menu()` "Tools" `sub_content`, add a BigQuery row (top of the Tools list, before "Web fetch"):

```python
                    _builtin_tool_item("database", "BigQuery (AJ360)",
                                       AppState.bigquery_on, AppState.toggle_bigquery),
```

- [ ] **Step 10: Run the state test + full frontend suite**

```bash
cd frontend
../venv312/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider
```
Expected: PASS (all, including the two new tests).

- [ ] **Step 11: Lint**

```bash
cd frontend
../venv312/Scripts/python.exe -m ruff check ocd_app/ tests/
```
Expected: `All checks passed!` (fix import order with `ruff check --fix` if needed).

- [ ] **Step 12: Commit**

```bash
git add frontend/ocd_app/api_client.py frontend/ocd_app/state.py \
        frontend/ocd_app/components/composer.py frontend/tests/test_api_client.py \
        frontend/tests/test_tool_persistence.py
git commit -m "feat(frontend): persist tool selection per conversation + optional BigQuery toggle"
```

---

## Task 6: End-to-end manual verification

- [ ] **Step 1: Recreate the local SQLite DB (adds the new `tools` column)**

```bash
cd backend
DATABASE_URL='sqlite:///C:/…/scratchpad/ocd_local.db' \
  ../venv312/Scripts/python.exe -c "import os; from ocd_core.db.engine import reset_engine, init_db; reset_engine(); init_db(); print('ok')"
```
(Or delete the old `ocd_local.db` first — it is disposable.)

- [ ] **Step 2: Launch backend + frontend** (per the project runbook: SQLite `DATABASE_URL`, empty `APP_*`, then `uvicorn app.main:app` and `reflex run --backend-port 8001 --frontend-port 3000`).

- [ ] **Step 3: Browser-task persistence** — new chat, enable **Playwright** (BigQuery stays OFF), ask "clone this site"; it stays a browser task (no SQL). Restart the backend; reopen the conversation → Playwright still enabled, BigQuery still off; "Do it again" retries the browser task.

- [ ] **Step 4: BigQuery capability** — new chat, enable **BigQuery (AJ360)** in the composer Tools menu, ask a data question → `search_schema`/`run_sql` run. Reload → BigQuery still enabled.

- [ ] **Step 5: Default check** — brand-new chat has BigQuery OFF and no SQL tools; a plain question is answered without any BigQuery framing.

---

## Self-review notes (author)

- **Spec coverage:** Part 0 → Task 1; Part 1 → Tasks 2, 3, and Task 5 steps 1–8; Part 2 → Task 4 + Task 5 steps 7c/8c/9; testing/manual → Task 6. All spec sections mapped.
- **Type/name consistency:** `_current_tools`/`_apply_tools`, `bigquery_on`, `toggle_bigquery`, `AgentOptions.bigquery`, `run_turn(..., bigquery=…)`, `save_conversation(..., tools=…)`, `Conversation.tools`, migration revision `a1b2c3d4e5f6` — all used consistently across tasks.
- **Ordering:** rename first (Task 1) so every later `frontend/ocd_app/...` path is valid; backend tasks (2–4) are independent of the rename; frontend wiring (Task 5) depends on both.
