"""Reflex application state for the Open Claude Desktop Projects UI."""
from __future__ import annotations

import asyncio
import os
import time

import reflex as rx

from . import api_client
from . import format as fmt

MEMORY_TURNS = 12

# --- Static UI config (pure, no I/O) ------------------------------------- #
# These were previously read through the now-deleted ``core`` shim from the
# backend config. The thin frontend has no backend code dependency, so these
# presentation-only constants are inlined here (verbatim from the backend
# config module). They drive class-body defaults and @rx.var comparisons,
# which cannot perform async network I/O.
GENERAL_ID = "general"
GENERAL_NAME = "General"
MAX_TABLE_ROWS_UI = 50
AGENT_MODEL = os.getenv("AGENT_MODEL", os.getenv("PLANNER_MODEL", "glm-4-plus"))
_GLM_DEFAULT = f"{AGENT_MODEL},glm-4.5-air,glm-4-flash,glm-4-long"
GLM_MODELS = list(dict.fromkeys(
    m.strip() for m in os.getenv("GLM_MODELS", _GLM_DEFAULT).split(",") if m.strip()))
EFFORT_LEVELS = ["Low", "Medium", "High", "Max"]
EFFORT_DESCRIPTIONS = {
    "Low": "Fast, direct answers",
    "Medium": "A little more checking",
    "High": "Plans before answering",
    "Max": "Plans, then self-verifies",
}


def _rows_to_markdown(columns: list, rows: list) -> str:
    """Render query rows as a compact GitHub-flavored Markdown table."""
    if not columns:
        return "_(no rows)_"

    def cell(v) -> str:
        s = str(v).replace("\n", " ").replace("|", "\\|")
        return s[:60] + ("…" if len(s) > 60 else "")

    head = "| " + " | ".join(str(c) for c in columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = ["| " + " | ".join(cell(r.get(c, "")) for c in columns) + " |" for r in rows]
    return "\n".join([head, sep, *body])


_REAUTH_HINTS = (
    "reauthentication is needed", "reauthentication failed",
    "invalid_grant", "application-default login",
)


def _looks_like_reauth(text: str) -> bool:
    """Heuristic: does an agent/tool error mean BigQuery ADC needs re-login?"""
    t = (text or "").lower()
    return any(h in t for h in _REAUTH_HINTS)


def _time_greeting(hour: int) -> str:
    """Time-of-day greeting from a 24-hour clock hour."""
    if 5 <= hour < 12:
        return "Good morning"
    if 12 <= hour < 18:
        return "Good afternoon"
    return "Good evening"


class AppState(rx.State):
    # ---- shell ----
    section: str = "chat"   # active top tab: chat | cowork | code
    greeting: str = "Good evening"   # chat-home time-of-day greeting

    # ---- backend health (startup ping) ----
    backend_ok: bool = True
    backend_error: str = ""

    # ---- BigQuery reconnect (ADC re-login) ----
    bq_auth_expired: bool = False
    bq_reconnecting: bool = False
    bq_reconnect_msg: str = ""

    # ---- dashboard ----
    projects: list[dict] = []
    search: str = ""

    # ---- workspace ----
    current_id: str = ""
    current_name: str = ""
    instructions: str = ""
    instructions_draft: str = ""
    editing_instructions: bool = False
    memory_text: str = ""
    memory_updated: str = ""
    files: list[dict] = []
    cap_used: float = 0.0
    cap_max: float = 50.0
    cap_pct: int = 0
    model: str = AGENT_MODEL
    effort: str = "High"
    effort_levels: list[str] = EFFORT_LEVELS
    effort_descriptions: dict[str, str] = EFFORT_DESCRIPTIONS
    model_options: list[str] = GLM_MODELS
    settings_saved: bool = False
    uploading: bool = False

    # ---- conversations (Claude-style threads) ----
    conversations: list[dict] = []      # current project's conversations
    recents: list[dict] = []            # global sidebar Recents (all projects)
    all_chats: list[dict] = []          # Chats dashboard
    chats_search: str = ""
    current_conv_id: str = ""
    conv_title: str = ""
    conv_pinned: bool = False

    # ---- rename / change-project dialogs ----
    rename_open: bool = False
    rename_draft: str = ""
    change_open: bool = False
    # Move-destination list (Projects + General); materialized on load because a
    # computed @rx.var cannot perform the async project fetch.
    move_targets: list[dict] = []

    # ---- Code (SQL console) ----
    code_sql: str = ""
    code_md: str = ""
    code_info: str = ""
    code_running: bool = False

    # ---- Artifacts ----
    all_files: list[dict] = []

    # ---- Chats dashboard: filter + bulk select ----
    chats_filter: str = "All"
    select_mode: bool = False
    selected_ids: list[str] = []

    # ---- active chat transcript (of the open conversation) ----
    # Message dicts are str-valued so rx.foreach can iterate them. Thinking blocks
    # encode done as "0"/"1"; the sources block stores its items list (cast with
    # .to(list[...]) at render time). Timing lives in backend-only vars below.
    messages: list[dict[str, str]] = []
    chat_input: str = ""
    is_running: bool = False
    # indices of expanded collapsible blocks in the transcript (in-memory; reopened
    # conversations render collapsed, matching Claude).
    expanded_thoughts: set[int] = set()
    expanded_sources: set[int] = set()
    expanded_tools: set[int] = set()
    # backend-only (leading underscore = not serialized to the client): elapsed-time
    # bookkeeping for the currently-open thinking block.
    _think_start: float = 0.0
    _think_elapsed: int = 0

    # ---- composer "+" menu ----
    web_search_on: bool = False
    research_on: bool = False
    # ---- Claude-equivalent built-in tools (web_fetch safe/ON; the rest OFF) ----
    web_fetch_on: bool = True
    code_exec_on: bool = False
    bash_on: bool = False
    text_editor_on: bool = False
    memory_on: bool = False
    bigquery_on: bool = False             # optional BigQuery capability, default OFF
    active_skill: str = ""               # name of the applied skill ("" = none)
    skills: list[dict] = []
    plugins: list[dict] = []
    enabled_plugins: list[str] = []
    connectors: list[dict] = []
    enabled_connectors: list[str] = []   # REST connector names exposed as tools
    connectors_attention: int = 0
    github_open: bool = False
    github_url: str = ""
    github_status: str = ""
    attach_open: bool = False
    attach_status: str = ""

    # ---- Connectors management page ----
    conn_add_open: bool = False
    conn_name: str = ""
    conn_url: str = ""
    conn_hkey: str = ""
    conn_hval: str = ""
    conn_test: str = ""

    # ---- MCP (Model Context Protocol) connectors ----
    mcp_servers: list[dict] = []
    enabled_mcp: list[str] = []
    mcp_add_open: bool = False
    mcp_name: str = ""
    mcp_command: str = ""
    mcp_args: str = ""
    mcp_status: str = ""

    # ---- new-project dialog ----
    show_new_dialog: bool = False
    new_name: str = ""
    new_desc: str = ""

    # --------------------------------------------------------------- #
    #  Dashboard
    # --------------------------------------------------------------- #
    async def _load_recents(self):
        """Global sidebar Recents + persisted settings (loaded on every page)."""
        self.recents = await api_client.list_all_conversations(limit=25)
        s = await api_client.get_settings()
        self.model = s["model"]
        self.effort = s["effort"]
        self.section = "chat"
        if not self.skills:
            self.skills = await api_client.list_skills()
        if not self.plugins:
            self.plugins = await api_client.list_plugins()
        await self.load_connectors()  # re-probe each page so status is never stale
        await self.load_mcp_servers()
        await self._refresh_move_targets()

    # --------------------------------------------------------------- #
    #  Composer "+" menu
    # --------------------------------------------------------------- #
    async def load_connectors(self):
        self.connectors = await api_client.list_connectors()
        self.connectors_attention = sum(
            1 for c in self.connectors if c["status"] == "error")

    # ---- Connectors management page (/connectors) ----
    async def load_connectors_page(self):
        await self._load_recents()
        self.conn_test = ""

    def toggle_connector(self, cid: str):
        if cid in self.enabled_connectors:
            self.enabled_connectors = [x for x in self.enabled_connectors if x != cid]
        else:
            self.enabled_connectors = [*self.enabled_connectors, cid]

    # ---- transcript collapsibles (thinking blocks + source sections) ----
    def toggle_thought(self, idx: int):
        s = set(self.expanded_thoughts)
        s.discard(idx) if idx in s else s.add(idx)
        self.expanded_thoughts = s

    def toggle_sources(self, idx: int):
        s = set(self.expanded_sources)
        s.discard(idx) if idx in s else s.add(idx)
        self.expanded_sources = s

    def toggle_tool(self, idx: int):
        s = set(self.expanded_tools)
        s.discard(idx) if idx in s else s.add(idx)
        self.expanded_tools = s

    # ---- MCP connectors ----
    async def load_mcp_servers(self):
        self.mcp_servers = await api_client.list_mcp_servers()

    def toggle_mcp(self, sid: str):
        if sid in self.enabled_mcp:
            self.enabled_mcp = [x for x in self.enabled_mcp if x != sid]
        else:
            self.enabled_mcp = [*self.enabled_mcp, sid]

    def open_add_mcp(self):
        self.mcp_name = self.mcp_command = self.mcp_args = self.mcp_status = ""
        self.mcp_add_open = True

    def set_mcp_add_open(self, v: bool):
        self.mcp_add_open = v

    def set_mcp_name(self, v: str):
        self.mcp_name = v

    def set_mcp_command(self, v: str):
        self.mcp_command = v

    def set_mcp_args(self, v: str):
        self.mcp_args = v

    async def save_mcp_server(self):
        cmd = self.mcp_command.strip()
        name = self.mcp_name.strip()
        if not (cmd and name):
            self.mcp_status = "Name and command are required."
            return
        args = [a for a in self.mcp_args.split() if a]
        self.mcp_status = f"Connecting to {name}…"
        yield
        item = await api_client.add_mcp_server(name, cmd, args)
        await self.load_mcp_servers()
        if item.get("status") == "connected":
            self.enabled_mcp = [*[x for x in self.enabled_mcp if x != item["id"]],
                                item["id"]]
            self.mcp_add_open = False
            self.mcp_status = ""
        else:
            self.mcp_status = f"Failed: {item.get('detail', 'unknown error')}"
        yield

    async def remove_mcp(self, sid: str):
        await api_client.remove_mcp_server(sid)
        self.enabled_mcp = [x for x in self.enabled_mcp if x != sid]
        await self.load_mcp_servers()

    def open_add_connector(self):
        self.conn_name = self.conn_url = self.conn_hkey = self.conn_hval = ""
        self.conn_add_open = True

    def set_conn_add_open(self, v: bool):
        self.conn_add_open = v

    def set_conn_name(self, v: str):
        self.conn_name = v

    def set_conn_url(self, v: str):
        self.conn_url = v

    def set_conn_hkey(self, v: str):
        self.conn_hkey = v

    def set_conn_hval(self, v: str):
        self.conn_hval = v

    async def save_connector(self):
        if self.conn_name.strip() and self.conn_url.strip():
            await api_client.add_connector(self.conn_name, self.conn_url,
                                           self.conn_hkey, self.conn_hval)
            self.conn_add_open = False
            await self.load_connectors()

    async def remove_user_connector(self, cid: str):
        await api_client.remove_connector(cid)
        self.enabled_connectors = [x for x in self.enabled_connectors if x != cid]
        await self.load_connectors()

    async def test_user_connector(self, cid: str):
        self.conn_test = f"Testing {cid}…"
        yield
        result = await api_client.test_connector(cid)
        self.conn_test = f"{cid}: {result}"
        yield

    def toggle_web_search(self):
        self.web_search_on = not self.web_search_on

    def toggle_research(self):
        self.research_on = not self.research_on

    # ---- Claude-equivalent built-in tool toggles ----
    def toggle_web_fetch(self):
        self.web_fetch_on = not self.web_fetch_on

    def toggle_code_exec(self):
        self.code_exec_on = not self.code_exec_on

    def toggle_bash(self):
        self.bash_on = not self.bash_on

    def toggle_text_editor(self):
        self.text_editor_on = not self.text_editor_on

    def toggle_memory(self):
        self.memory_on = not self.memory_on

    def toggle_bigquery(self):
        self.bigquery_on = not self.bigquery_on

    def apply_skill(self, name: str):
        self.active_skill = "" if self.active_skill == name else name

    def toggle_plugin(self, name: str):
        if name in self.enabled_plugins:
            self.enabled_plugins = [x for x in self.enabled_plugins if x != name]
        else:
            self.enabled_plugins = [*self.enabled_plugins, name]

    @rx.var
    def model_label(self) -> str:
        return f"{self.model} · {self.effort}"

    @rx.var
    def active_modes(self) -> list[str]:
        """Mode chips to surface in the composer (Research / Web / Skill)."""
        chips = []
        if self.research_on:
            chips.append("Research")
        elif self.web_search_on:
            chips.append("Web")
        if self.web_fetch_on:
            chips.append("Fetch")
        if self.code_exec_on:
            chips.append("Code")
        if self.bash_on:
            chips.append("Bash")
        if self.text_editor_on:
            chips.append("Editor")
        if self.memory_on:
            chips.append("Memory")
        if self.bigquery_on:
            chips.append("BigQuery")
        if self.active_skill:
            chips.append(self.active_skill)
        return chips

    async def select_model(self, m: str):
        self.model = m
        await api_client.save_settings({"model": m, "effort": self.effort})

    async def select_effort(self, level: str):
        self.effort = level
        await api_client.save_settings({"model": self.model, "effort": level})

    # ---- Add from GitHub ----
    def open_github(self):
        self.github_url = ""
        self.github_status = ""
        self.github_open = True

    def set_github_open(self, value: bool):
        self.github_open = value

    def set_github_url(self, v: str):
        self.github_url = v

    async def run_github_import(self):
        url = self.github_url.strip()
        pid = self.current_id or GENERAL_ID
        if not url:
            return
        self.github_status = "Importing…"
        yield
        res = await api_client.import_github_repo(url, pid)
        if res["message"]:
            self.github_status = f"Failed: {res['message']}"
        else:
            self.github_status = (
                f"Imported {res['chunks']} file(s) into this project's KB.")
            if pid != GENERAL_ID:
                await self._refresh_files()
        yield

    # ---- Add files dialog ----
    def open_attach(self):
        self.attach_open = True

    def set_attach_open(self, value: bool):
        self.attach_open = value

    # --------------------------------------------------------------- #
    #  Customize (settings)
    # --------------------------------------------------------------- #
    async def load_customize(self):
        await self._load_recents()
        self.settings_saved = False

    async def set_effort(self, v: str):
        self.effort = v
        await api_client.save_settings({"model": self.model, "effort": v})

    async def save_customize(self):
        await api_client.save_settings({"model": self.model, "effort": self.effort})
        self.settings_saved = True

    async def load_dashboard(self):
        self.projects = await api_client.list_project_cards()
        await self._load_recents()

    async def check_backend(self):
        """Startup health ping; surfaces a banner when the API is unreachable."""
        try:
            await api_client.health()
            self.backend_ok = True
            self.backend_error = ""
        except Exception as e:
            self.backend_ok = False
            self.backend_error = f"Backend unreachable at {api_client._BASE}: {e}"

    # --------------------------------------------------------------- #
    #  Chats dashboard (/chats) — all conversations across projects
    # --------------------------------------------------------------- #
    async def load_chats(self):
        self.all_chats = await api_client.list_all_conversations(limit=200)
        await self._load_recents()

    def set_chats_search(self, v: str):
        self.chats_search = v

    @rx.var
    def filtered_chats(self) -> list[dict]:
        q = self.chats_search.strip().lower()
        items = self.all_chats
        if self.chats_filter != "All":
            items = [c for c in items if c["project_name"] == self.chats_filter]
        if q:
            items = [c for c in items
                     if q in c["title"].lower() or q in c["project_name"].lower()]
        return items

    @rx.var
    def has_chats(self) -> bool:
        return len(self.all_chats) > 0

    @rx.var
    def project_filter_options(self) -> list[str]:
        names = sorted({c["project_name"] for c in self.all_chats})
        return ["All", *names]

    @rx.var
    def selected_count(self) -> int:
        return len(self.selected_ids)

    # ---- Code (SQL console) ----
    def set_code_sql(self, v: str):
        self.code_sql = v

    async def load_code(self):
        await self._load_recents()
        self.section = "code"

    async def run_code(self, form_data: dict | None = None):
        sql = self.code_sql.strip()
        if not sql or self.code_running:
            return
        self.code_running = True
        self.code_md = ""
        self.code_info = "Running…"
        yield
        res = await api_client.execute_sql(sql, None)
        if res.get("ok"):
            self.code_md = _rows_to_markdown(res["columns"],
                                             res["rows"][:MAX_TABLE_ROWS_UI])
            self.code_info = (f"{res['total_rows']} rows · "
                              f"{fmt.fmt_bytes(res['bytes'])} scanned")
        else:
            self.code_md = ""
            self.code_info = res.get("agent_text", res.get("error", "Failed"))
        self.code_running = False
        yield

    # ---- Artifacts ----
    async def load_artifacts(self):
        self.all_files = await api_client.list_all_files()
        await self._load_recents()

    @rx.var
    def has_artifacts(self) -> bool:
        return len(self.all_files) > 0

    # ---- Cowork / New chat (General space) ----
    async def load_cowork(self):
        await self._load_project_context(GENERAL_ID)
        self.conversations = await api_client.list_conversations(GENERAL_ID)
        await self._load_recents()
        self.messages = []
        self.current_conv_id = ""
        self.conv_title = ""
        self.chat_input = ""
        self.is_running = False
        self.section = "cowork"

    def new_chat(self):
        return rx.redirect("/")

    async def load_home(self):
        """The Claude-style chat home (General space) at /."""
        await self._load_project_context(GENERAL_ID)
        self.conversations = await api_client.list_conversations(GENERAL_ID)
        await self._load_recents()
        self.messages = []
        self.current_conv_id = ""
        self.conv_title = ""
        self.chat_input = ""
        self.is_running = False
        self.section = "chat"
        self.greeting = _time_greeting(time.localtime().tm_hour)

    def goto_home(self):
        return rx.redirect("/")

    def chip_query_bigquery(self):
        self.chat_input = "Query BigQuery: "

    # ---- Pin / Change project / Remove from project ----
    async def toggle_pin(self):
        if self.current_id and self.current_conv_id:
            self.conv_pinned = not self.conv_pinned
            await api_client.set_conversation_pinned(
                self.current_id, self.current_conv_id, self.conv_pinned)
            await self._load_recents()

    async def open_change_project(self):
        await self._refresh_move_targets()
        self.change_open = True

    def set_change_open(self, value: bool):
        self.change_open = value

    async def _refresh_move_targets(self):
        """Populate the move-destination list (Projects + General) the current
        conversation can move to. Backing field for the move submenu + dialog
        (a computed @rx.var can't be async, so we materialize it on load)."""
        targets = [{"id": GENERAL_ID, "name": GENERAL_NAME}]
        targets += [{"id": p["id"], "name": p["name"]}
                    for p in await api_client.list_projects()]
        self.move_targets = [t for t in targets if t["id"] != self.current_id]

    async def move_to_project(self, dst_pid: str):
        src, cid = self.current_id, self.current_conv_id
        self.change_open = False
        if not dst_pid:
            return
        if cid:
            # Existing conversation → move the file and follow it.
            await api_client.move_conversation(src, cid, dst_pid)
            return rx.redirect(f"/project/{dst_pid}/c/{cid}")
        # New-chat composer (no conversation yet): carry the typed draft into a
        # new conversation in the destination, else just open that workspace.
        text = self.chat_input.strip()
        if text:
            conv = await api_client.create_conversation(dst_pid, text)
            self.chat_input = ""
            return rx.redirect(f"/project/{dst_pid}/c/{conv['id']}")
        return rx.redirect(f"/project/{dst_pid}")

    async def remove_from_project(self):
        src, cid = self.current_id, self.current_conv_id
        if src and cid and src != GENERAL_ID:
            await api_client.move_conversation(src, cid, GENERAL_ID)
        return rx.redirect(f"/project/{GENERAL_ID}/c/{cid}")

    # ---- Chats dashboard: filter + bulk select ----
    def set_chats_filter(self, v: str):
        self.chats_filter = v

    def toggle_select_mode(self):
        self.select_mode = not self.select_mode
        self.selected_ids = []

    def toggle_selected(self, conv_id: str):
        if conv_id in self.selected_ids:
            self.selected_ids = [x for x in self.selected_ids if x != conv_id]
        else:
            self.selected_ids = [*self.selected_ids, conv_id]

    async def bulk_delete(self):
        sel = set(self.selected_ids)
        for c in self.all_chats:
            if c["id"] in sel:
                await api_client.delete_conversation(c["project_id"], c["id"])
        self.selected_ids = []
        self.select_mode = False
        self.all_chats = await api_client.list_all_conversations(limit=200)
        await self._load_recents()

    # ---- input setters (explicit; Reflex no longer auto-generates) ----
    def set_search(self, v: str):
        self.search = v

    def set_new_name(self, v: str):
        self.new_name = v

    def set_new_desc(self, v: str):
        self.new_desc = v

    def set_instructions_draft(self, v: str):
        self.instructions_draft = v

    def set_model(self, v: str):
        self.model = v

    def set_chat_input(self, v: str):
        self.chat_input = v

    @rx.var
    def filtered_projects(self) -> list[dict]:
        q = self.search.strip().lower()
        if not q:
            return self.projects
        return [p for p in self.projects
                if q in p["name"].lower() or q in p["desc"].lower()]

    @rx.var
    def has_projects(self) -> bool:
        return len(self.projects) > 0

    def open_new_dialog(self):
        self.new_name = ""
        self.new_desc = ""
        self.show_new_dialog = True

    def set_new_dialog(self, value: bool):
        self.show_new_dialog = value

    async def create_project(self):
        name = self.new_name.strip()
        if not name:
            return
        meta = await api_client.create_project(name)
        if self.new_desc.strip():
            await api_client.save_project_instructions(meta["id"],
                                                       self.new_desc.strip())
        self.show_new_dialog = False
        await self.load_dashboard()
        return rx.redirect(f"/project/{meta['id']}")

    def open_project(self, pid: str):
        self.current_id = pid
        return rx.redirect(f"/project/{pid}")

    async def delete_current_project(self):
        if self.current_id:
            await api_client.delete_project(self.current_id)
        return rx.redirect("/projects")

    # --------------------------------------------------------------- #
    #  Workspace
    # --------------------------------------------------------------- #
    def _route_param(self, name: str) -> str:
        try:
            return self.router.page.params.get(name, "")
        except Exception:
            try:
                return self.router._page.params.get(name, "")  # type: ignore[attr-defined]
            except Exception:
                return ""

    def _pid(self) -> str:
        return self._route_param("pid") or self.current_id

    def _cid(self) -> str:
        return self._route_param("cid") or self.current_conv_id

    @rx.var
    def workspace_href(self) -> str:
        if self.current_id == GENERAL_ID:
            return "/"
        return f"/project/{self.current_id}"

    @rx.var
    def is_general(self) -> bool:
        return self.current_id == GENERAL_ID

    async def _load_project_context(self, pid: str) -> dict | None:
        if pid == GENERAL_ID:
            self.current_id = pid
            self.current_name = GENERAL_NAME
            self.instructions = ""
            self.instructions_draft = ""
            self.editing_instructions = False
            self.memory_text, self.memory_updated = "", ""
            self.files = []
            self.cap_used, self.cap_pct = 0.0, 0
            return {"id": pid, "name": GENERAL_NAME}
        try:
            proj = await api_client.get_project(pid)
        except api_client.ApiError:
            proj = None
        if not proj:
            return None
        self.current_id = pid
        self.current_name = proj.get("name", "Untitled")
        self.instructions = await api_client.get_project_instructions(pid)
        self.instructions_draft = self.instructions
        self.editing_instructions = False
        self.memory_text, self.memory_updated = (
            await api_client.get_project_memory(pid))
        await self._refresh_files()
        return proj

    async def load_workspace(self):
        await self.load_dashboard()  # populate the sidebar project list on deep-links too
        pid = self._pid()
        if not await self._load_project_context(pid):
            return rx.redirect("/")
        self.conversations = await api_client.list_conversations(pid)
        await self._load_recents()
        self.messages = []
        self.current_conv_id = ""
        self.conv_title = ""
        self.chat_input = ""
        self.is_running = False

    async def _refresh_files(self):
        self.files = await api_client.list_project_files(self.current_id)
        cap = await api_client.project_capacity(self.current_id)
        self.cap_used = cap["used_mb"]
        self.cap_max = cap["max_mb"]
        self.cap_pct = cap["percent"]

    @rx.var
    def instructions_display(self) -> str:
        t = self.instructions.strip()
        return t if t else "No instructions set yet. Click the pencil to add context."

    @rx.var
    def memory_display(self) -> str:
        t = self.memory_text.strip()
        if not t:
            return ("No memory yet. As you work in this project, key context will live "
                    "here. Add a memory.md in the project folder to seed it.")
        return t[:400] + ("…" if len(t) > 400 else "")

    @rx.var
    def has_files(self) -> bool:
        return len(self.files) > 0

    def start_edit_instructions(self):
        self.instructions_draft = self.instructions
        self.editing_instructions = True

    def cancel_edit_instructions(self):
        self.editing_instructions = False

    async def save_instructions(self):
        await api_client.save_project_instructions(self.current_id,
                                                   self.instructions_draft)
        self.instructions = self.instructions_draft
        self.editing_instructions = False

    # --------------------------------------------------------------- #
    #  Chat — consume the agent's event stream, render progressively
    # --------------------------------------------------------------- #
    @rx.var
    def can_send(self) -> bool:
        return not self.is_running and self.chat_input.strip() != ""

    def _chat_history(self) -> list[dict]:
        """Prior conversational turns (user + final answers only)."""
        hist: list[dict] = []
        for m in self.messages:
            if m["kind"] == "user":
                hist.append({"role": "user", "content": m["content"]})
            elif m["kind"] == "final":
                hist.append({"role": "assistant", "content": m["content"]})
        # The just-appended user message is the current goal — drop it from history.
        if hist and hist[-1]["role"] == "user":
            hist = hist[:-1]
        return hist[-MEMORY_TURNS:]

    # --- Composer (workspace): start a NEW conversation, then redirect to it --- #
    async def start_conversation(self, form_data: dict | None = None):
        text = self.chat_input.strip()
        if not text or self.is_running or not self.current_id:
            return
        conv = await api_client.create_conversation(self.current_id, text)
        self.chat_input = ""
        return rx.redirect(f"/project/{self.current_id}/c/{conv['id']}")

    # --- Conversation page on_load: render it, run agent if a turn is pending --- #
    async def load_conversation(self):
        await self.load_dashboard()
        pid = self._pid()
        if not await self._load_project_context(pid):
            yield rx.redirect("/")
            return
        cid = self._cid()
        try:
            conv = await api_client.get_conversation(pid, cid)
        except api_client.ApiError:
            conv = None
        if not conv:
            yield rx.redirect(f"/project/{pid}")
            return
        self.current_conv_id = cid
        self.conv_title = conv.get("title", "Conversation")
        self.conv_pinned = bool(conv.get("pinned", False))
        self.messages = self._normalize_messages(conv.get("messages", []))
        self._apply_tools(conv.get("tools") or {})
        self.expanded_thoughts = set()
        self.expanded_sources = set()
        self.expanded_tools = set()
        self.chat_input = ""
        self.is_running = False
        await self._load_recents()
        yield
        # A freshly-created conversation ends on the user's message → answer it.
        if self.messages and self.messages[-1].get("kind") == "user":
            goal = self.messages[-1]["content"]
            async for _ in self._run_agent(goal, pid, cid, first_turn=True):
                yield

    # --- Conversation page input: continue the CURRENT conversation --- #
    async def send_message(self, form_data: dict | None = None):
        text = self.chat_input.strip()
        if not text or self.is_running or not self.current_conv_id:
            return
        self.messages.append({"role": "user", "content": text, "kind": "user"})
        self.chat_input = ""
        await api_client.save_conversation(self.current_id, self.current_conv_id,
                                           self.messages, self.conv_title or None,
                                           self._current_tools())
        yield
        async for _ in self._run_agent(text, self.current_id, self.current_conv_id):
            yield

    @staticmethod
    def _normalize_messages(msgs: list) -> list:
        """Reopened conversations: legacy 'thought' rows and any thinking blocks
        render as finished + collapsed."""
        out = []
        for m in msgs:
            m = dict(m)
            if m.get("kind") in ("thinking", "thought"):
                m["kind"] = "thinking"
                m["done"] = "1"
                m.setdefault("phase", "plan")
                m.setdefault("label", m.get("label") or "Thought")
            elif m.get("kind") == "final" and m.get("content"):
                # Clean a stray "Corrected Answer" heading saved before the verify-
                # prompt fix, so legacy answers also read seamlessly.
                m["content"] = fmt.strip_answer_label(m["content"])
            elif m.get("kind") == "tool":
                # Reopened tool cards render finished + collapsed. Legacy flat tool
                # rows (only "content") become a generic done card.
                m["status"] = "done"
                m.setdefault("id", "")
                m.setdefault("name", "")
                m.setdefault("icon", "wrench")
                m.setdefault("label_done", "Used tool")
                m.setdefault("label_running", m.get("label_done", "Used tool"))
                m.setdefault("input", "")
                m.setdefault("summary", m.get("summary") or m.get("content", ""))
                m.setdefault("error", "")
            out.append(m)
        return out

    # --- Thinking-block coalescing: group consecutive reasoning into one collapsible
    #     "thinking" message (Claude-style), tracking live/done + elapsed seconds. --- #
    def _open_thinking(self, content: str, phase: str, elapsed: int):
        """Start a new collapsible thinking block and begin its timer."""
        self._close_thinking()
        self._think_start = time.monotonic()
        self._think_elapsed = int(elapsed or 0)
        self.messages.append({"role": "assistant", "content": content,
                              "kind": "thinking", "phase": phase,
                              "done": "0", "label": ""})

    def _append_thought(self, text: str, phase: str, elapsed: int):
        if not text:
            return
        last = self.messages[-1] if self.messages else None
        if (last and last.get("kind") == "thinking" and last.get("done") == "0"
                and last.get("phase") == phase):
            last["content"] = (last["content"] + "\n\n" + text).strip()
            if elapsed:
                self._think_elapsed = int(elapsed)
            self.messages = self.messages  # nudge reactivity
        else:
            self._open_thinking(text, phase, elapsed)

    def _close_thinking(self, elapsed: int = 0):
        """Mark the most-recent OPEN thinking block as done + finalize its label.
        Searches backwards so it works even when an answer bubble is trailing (the
        streamed verify pass: thinking block open above a streaming answer)."""
        for last in reversed(self.messages):
            if last.get("kind") == "thinking" and last.get("done") == "0":
                secs = (int(elapsed) or self._think_elapsed
                        or max(1, round(time.monotonic() - (self._think_start or
                                                            time.monotonic()))))
                last["done"] = "1"
                last["label"] = f"Thought for {secs}s" if secs else "Thought"
                self._think_elapsed = 0
                self.messages = self.messages  # nudge reactivity
                return

    # ---- Token streaming: append deltas to the live answer bubble / thinking block ----
    def _open_think_block(self):
        """Return the most-recent OPEN thinking block, creating one if none is open."""
        for m in reversed(self.messages):
            if m.get("kind") == "thinking" and m.get("done") == "0":
                return m
        self._open_thinking("", "narration", 0)
        return self.messages[-1]

    def _append_delta(self, scope: str, text: str):
        if not text:
            return
        if scope == "answer":
            if not (self.messages and self.messages[-1].get("kind") == "final"):
                self.messages.append({"role": "assistant", "content": "",
                                      "kind": "final"})
            self.messages[-1]["content"] = self.messages[-1]["content"] + text
        else:  # "think"
            blk = self._open_think_block()
            blk["content"] = blk["content"] + text
        self.messages = self.messages  # nudge reactivity

    def _answer_to_think(self, phase: str, elapsed: int):
        """Fold a streamed answer bubble into a (done) thinking block — used when the
        streamed content turns out to be narration or a pre-verify draft. Drops the
        bubble if it's empty."""
        if not self.messages or self.messages[-1].get("kind") != "final":
            return
        last = self.messages[-1]
        if not (last.get("content") or "").strip():
            self.messages.pop()
            self.messages = self.messages
            return
        secs = int(elapsed) or self._think_elapsed or 1
        last["kind"] = "thinking"
        last["phase"] = phase
        last["done"] = "1"
        last["label"] = f"Thought for {secs}s" if secs else "Thought"
        self._think_elapsed = 0
        self.messages = self.messages  # nudge reactivity

    def _update_tool(self, tid: str, **fields):
        """Update the tool card with this id in place (status running→done/error)."""
        for m in self.messages:
            if m.get("kind") == "tool" and m.get("id") == tid:
                m.update(fields)
                break
        self.messages = self.messages  # nudge reactivity

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
                "bigquery": self.bigquery_on,
            },
            "enabled_plugins": list(self.enabled_plugins),
            "enabled_connectors": list(self.enabled_connectors),
            "enabled_mcp": list(self.enabled_mcp),
        }

    # --- BigQuery reconnect (ADC re-login) --- #
    async def reconnect_bigquery(self):
        """Trigger gcloud ADC re-login on the backend, then poll until connected."""
        self.bq_reconnecting = True
        self.bq_reconnect_msg = "Opening Google sign-in in your browser…"
        yield
        try:
            res = await api_client.bigquery_reconnect()
        except Exception as e:
            self.bq_reconnecting = False
            self.bq_reconnect_msg = f"Couldn't start reconnect: {e}"
            return
        if not res.get("started"):
            self.bq_reconnecting = False
            self.bq_reconnect_msg = res.get("error", "Reconnect failed.")
            return
        self.bq_reconnect_msg = "Complete the Google sign-in; this clears when reconnected…"
        yield
        for _ in range(30):  # poll ~60s
            await asyncio.sleep(2)
            try:
                st = await api_client.bigquery_status()
            except Exception:
                st = {}
            if st.get("connected"):
                self.bq_auth_expired = False
                self.bq_reconnecting = False
                self.bq_reconnect_msg = "Reconnected ✓ — retry your question."
                yield
                return
            yield
        self.bq_reconnecting = False
        self.bq_reconnect_msg = "Sign-in didn't complete — try again."
        yield

    # --- Shared agent runner: stream events into the transcript, then persist --- #
    async def _run_agent(self, goal: str, pid: str, cid: str, first_turn: bool = False):
        self.is_running = True
        yield
        try:
            async for ev in api_client.run_agent_stream(
                    self._build_turn_request(goal, pid)):
                t = ev["type"]
                if t == "thought":
                    self._append_thought(ev.get("text", ""), ev.get("phase", "plan"),
                                         int(ev.get("elapsed", 0) or 0))
                elif t == "verify":
                    self._open_thinking(ev["text"], "verify", 0)
                elif t == "delta":
                    self._append_delta(ev.get("scope", "answer"), ev.get("text", ""))
                elif t == "think_open":
                    self._open_thinking("", ev.get("phase", "plan"), 0)
                elif t == "think_close":
                    self._close_thinking(int(ev.get("elapsed", 0) or 0))
                elif t == "answer_open":
                    self.messages.append({"role": "assistant", "content": "",
                                          "kind": "final"})
                elif t == "answer_to_think":
                    self._answer_to_think(ev.get("phase", "narration"),
                                          int(ev.get("elapsed", 0) or 0))
                elif t == "tool":
                    # One stateful tool CARD per call (status running→done→error),
                    # upserted by id so the later result/error updates this same card.
                    self._close_thinking()
                    self.messages.append({
                        "role": "tool", "kind": "tool", "id": str(ev["id"]),
                        "name": ev["name"], "icon": ev.get("icon", "wrench"),
                        "label_running": ev.get("label_running", "Using tool"),
                        "label_done": ev.get("label_done", "Used tool"),
                        "input": ev.get("input", ""), "status": "running",
                        "summary": "", "error": ""})
                elif t == "tool_result":
                    self._update_tool(str(ev["id"]), status="done",
                                      summary=ev.get("summary", ""))
                elif t == "tool_error":
                    self._update_tool(str(ev["id"]), status="error",
                                      error=ev.get("text", "Tool failed."))
                elif t == "sources":
                    self.messages.append({"role": "tool", "kind": "sources",
                                          "items": ev["items"]})
                elif t == "table":
                    cap = f"**{ev['total']} rows · {fmt.fmt_bytes(ev['bytes'])} scanned**"
                    md = _rows_to_markdown(ev["columns"], ev["rows"])
                    self.messages.append({"role": "tool", "content": f"{cap}\n\n{md}",
                                          "kind": "table"})
                elif t == "final":
                    self._close_thinking(int(ev.get("verify_elapsed", 0) or 0))
                    self.messages.append({"role": "assistant", "content": ev["text"],
                                          "kind": "final"})
                elif t == "error":
                    self._close_thinking()
                    if _looks_like_reauth(ev["text"]):
                        self.bq_auth_expired = True
                    self.messages.append({"role": "assistant", "content": ev["text"],
                                          "kind": "error"})
                yield
        except Exception as e:
            self.messages.append({"role": "assistant", "content": f"Agent error: {e}",
                                  "kind": "error"})
        self.is_running = False
        await api_client.save_conversation(pid, cid, self.messages,
                                           self.conv_title or None, self._current_tools())
        yield
        # Give a freshly-created conversation a concise Claude-style title.
        if first_turn and pid and cid:
            try:
                title = await api_client.generate_conversation_title(goal)
                if title:
                    self.conv_title = title
                    await api_client.set_conversation_title(pid, cid, title)
                    yield
            except Exception:
                pass

    async def delete_current_conversation(self):
        pid = self.current_id
        if pid and self.current_conv_id:
            await api_client.delete_conversation(pid, self.current_conv_id)
        return rx.redirect(f"/project/{pid}")

    # --- Rename current conversation (breadcrumb menu) --- #
    def open_rename(self):
        self.rename_draft = self.conv_title
        self.rename_open = True

    def set_rename_open(self, value: bool):
        self.rename_open = value

    def set_rename_draft(self, v: str):
        self.rename_draft = v

    async def save_rename(self):
        title = self.rename_draft.strip()
        if title and self.current_id and self.current_conv_id:
            await api_client.set_conversation_title(
                self.current_id, self.current_conv_id, title)
            self.conv_title = title
            await self._load_recents()
        self.rename_open = False

    async def handle_upload(self, files: list[rx.UploadFile]):
        self.uploading = True
        yield
        ok, failed = 0, []
        for f in files:
            name = getattr(f, "name", None) or getattr(f, "filename", "upload.bin")
            try:
                data = await f.read()
                await api_client.upload_file(self.current_id, name, data)
                ok += 1
            except Exception as e:
                failed.append(f"{name}: {e}")
        await self._refresh_files()
        self.all_files = await api_client.list_all_files()   # keep /artifacts in sync
        self.uploading = False
        if failed:
            self.attach_status = (f"Uploaded {ok}; {len(failed)} failed: "
                                  f"{'; '.join(failed)[:160]}")
        else:
            self.attach_status = ""
            self.attach_open = False             # close only on full success
        yield
