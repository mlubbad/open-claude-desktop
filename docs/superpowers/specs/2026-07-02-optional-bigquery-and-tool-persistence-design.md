# Optional BigQuery capability + per-conversation tool persistence — design

**Date:** 2026-07-02
**Status:** Approved in brainstorming → spec for review

## Problem

Two compounding bugs made "clone this website" → "Do it again" silently turn into a
dozen unrelated BigQuery queries:

1. **Tool selection is ephemeral.** `enabled_mcp/plugins/connectors` + the built-in
   tool toggles live only in Reflex `AppState`, reset to defaults on any fresh
   connection (reload / backend restart). A browser (Playwright MCP) tool enabled for
   turn 1 vanished before turn 2 — nothing ties tool state to the conversation.
2. **BigQuery is hard-wired.** `agent.py` always injects `search_schema`/`run_sql` and a
   system prompt that declares *"You are a BigQuery analytics agent … loop: search_schema
   → SQL → run_sql."* When the browser tool disappeared, the model had only BigQuery tools
   and a BigQuery identity, so it warped the request into schema/SQL exploration.

## Goals

1. Tool/capability selection **persists per conversation** and is restored on load.
2. **BigQuery becomes an optional, user-configurable capability** (default **OFF** for new
   conversations), not the agent's hard-wired identity. The system prompt frames BigQuery
   only when the capability is enabled.
3. Rename the frontend Reflex package `aj360_app` → **`ocd_app`** (aligns with the backend
   `ocd_core` / `ocd-backend`).

## Non-goals (explicit)

- No missing-tool "honesty guard" and no injecting the live tool list into the prompt
  (considered, deferred by request).
- No extraction of BigQuery into a standalone external MCP-server process (larger/riskier;
  the in-process capability toggle below achieves the same UX).
- **No change** to BigQuery datasets (`aj360.*`), `AJ360_*` env vars, `GENERAL_ID`,
  branding, or backend `ocd_core` naming. The rename touches the frontend package only.
- No save-on-every-toggle; persistence happens at the existing per-turn save points.

## Part 0 — Rename `aj360_app` → `ocd_app` (prerequisite mechanical refactor)

- Rename dir `frontend/aj360_app/` → `frontend/ocd_app/`; inner entry `aj360_app.py` →
  `ocd_app.py`.
- `frontend/rxconfig.py`: `app_name="ocd_app"`; update the reload-path override
  (`REFLEX_HOT_RELOAD_OVERRIDE_PATHS`, currently `"aj360_app"`) → `"ocd_app"`.
- Update all absolute imports `aj360_app.*` → `ocd_app.*` (tests: `test_home.py`,
  `test_api_client.py`, `conftest.py`). Relative imports (`from .state import …`) are
  unchanged by the dir rename.
- Delete + let Reflex regenerate `frontend/.web` (it is app_name-specific).
- Repo-wide: update stray `aj360_app` references in frontend config/docs **only**. Leave
  every `aj360.*` / `AJ360_*` / backend reference untouched.
- **Verify:** frontend test suite green under `ocd_app`; `reflex run` compiles + serves at
  :3000.

## Part 1 — Persist tool/capability selection per conversation

**Backend**
- `Conversation` model: add `tools: dict = Field(default_factory=dict, sa_column=Column(JSON))`
  (mirrors the existing `transcript` JSON column).
- Alembic migration: `op.add_column("conversation", sa.Column("tools", sa.JSON(), nullable=True))`
  — applies to Postgres and SQLite. Existing local `ocd_local.db` picks it up on upgrade, or
  is recreated (disposable).
- `conversations.save_conversation(project_id, conv_id, messages, title=None, tools=None)`:
  persist `tools or {}`. `_to_dict()` / `get_conversation` include `tools`.
- `ConversationSave` schema: add `tools: dict | None = None`; PUT route forwards it.

**Frontend (`ocd_app/state.py`)**
- `_current_tools() -> dict` snapshots the full selection:
  `{plugins, connectors, mcp, web_search, research, web_fetch, code_exec, bash,
    text_editor, memory, skill, bigquery}`.
- `_apply_tools(tools: dict)` restores those AppState fields (leaves current defaults for
  keys absent in older records).
- Both existing `save_conversation` call sites (after the user message; after the agent
  turn — the sites the 422 fix touched) pass `self._current_tools()`.
- `load_conversation()` calls `_apply_tools(conv.get("tools") or {})`.
- `api_client.save_conversation(..., tools: dict | None = None)` forwards `tools` in the
  PUT body.

## Part 2 — BigQuery as an optional capability

**State / UI (`ocd_app/state.py`, `components/composer.py`)**
- `AppState.bigquery_on: bool = False` (default OFF). `toggle_bigquery` handler.
- Included in `_current_tools`/`_apply_tools` and shown as an `active_modes` chip when on.
- Composer plus-menu: a toggle row **"BigQuery (AJ360)"** (icon `database`) in the Tools
  section, checkmark when on — following the existing `_builtin_tool_item` pattern.

**Backend (`ocd_core/agent.py`, schemas, route)**
- `run_turn(...)` gains `bigquery: bool = False`. The BigQuery tools (`search_schema`,
  `run_sql`) are appended to the tool list **only when `bigquery=True`** (today they are the
  always-on base `TOOLS`).
- **Composed system prompt:**
  - `BASE_PROMPT` (generic): *"You are Open Claude Desktop, a helpful assistant. Use whatever
    tools are enabled this turn (which may include web search/fetch, a browser and other MCP
    connectors, code execution, and file editing) to accomplish the user's request. Be terse,
    evidence-first, American English."*
  - `BIGQUERY_PROMPT`: the current AJ360 operating loop + hard rules (project id, banned
    aliases, `devicetype`, `SAFE_DIVIDE`, `series_id`, default window, GA4 notes, …).
  - `_system_prompt(...)` appends `BIGQUERY_PROMPT` **only when `bigquery=True`** (alongside the
    existing conditional research/memory/project/skill blocks).
- `AgentOptions` (schema): add `bigquery: bool = False`. `agent_turn` route passes
  `o.bigquery` → `run_turn(..., bigquery=...)`.
- Frontend `_build_turn_request` includes `"bigquery": self.bigquery_on` in `options`.

**Behavior**
- New chat (BigQuery OFF): no `search_schema`/`run_sql`, no BigQuery framing — a
  "clone this website" turn uses the browser/other enabled tools and never pivots to SQL.
- BigQuery ON: identical AJ360 analytics behavior to today.

## Data flow (the fix, end to end)

Enable Playwright (and optionally BigQuery) in a chat → every turn's `save_conversation`
records the `tools` snapshot → reconnect/reload → `load_conversation` restores it → the next
turn / "Do it again" runs with the same tools and capability framing. A website-clone chat
stays a browser task; a data chat stays a data task.

## Testing

**Backend**
- `save_conversation`/`get_conversation` round-trip `tools`; PUT-then-GET route test.
- `agent`: assert `search_schema`/`run_sql` are ABSENT when `bigquery=False` and PRESENT when
  `True`; assert the system prompt contains the AJ360 rules only when `bigquery=True`.
- Migration applies cleanly (SQLite).

**Frontend**
- `_current_tools`/`_apply_tools` round-trip including `mcp` and `bigquery`.
- `api_client.save_conversation` sends `tools` (respx).
- Full suite passes under the renamed `ocd_app` package.

**Manual**
- New chat → BigQuery off; enable Playwright; "clone site" stays a browser task; restart
  backend; reopen → Playwright still on, BigQuery still off; "Do it again" retries the browser.
- Another chat → enable BigQuery; a data question runs `search_schema`/`run_sql`; state
  persists across reload.

## Compatibility

- Conversations saved before this change have no `tools` → open with defaults (BigQuery off,
  `web_fetch` on, no MCP). Acceptable.
- The AJ360 analytics **skills** (daily-insights, etc.) now require BigQuery toggled on for
  that chat. Auto-enabling BigQuery when such a skill is applied is a possible future
  enhancement, out of scope here.
