"""Reflex application state for the Open Claude Desktop Projects UI."""
from __future__ import annotations

import time
import asyncio

import reflex as rx

from . import core
from . import agent
from . import integrations

MEMORY_TURNS = 12


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


class AppState(rx.State):
    # ---- shell ----
    section: str = "chat"   # active top tab: chat | cowork | code

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
    model: str = core.AGENT_MODEL
    effort: str = "High"
    effort_levels: list[str] = core.EFFORT_LEVELS
    effort_descriptions: dict[str, str] = core.EFFORT_DESCRIPTIONS
    model_options: list[str] = core.GLM_MODELS
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
    def _load_recents(self):
        """Global sidebar Recents + persisted settings (loaded on every page)."""
        self.recents = core.list_all_conversations(limit=25)
        s = core.get_settings()
        self.model = s["model"]
        self.effort = s["effort"]
        self.section = "chat"
        if not self.skills:
            self.skills = integrations.list_skills()
        if not self.plugins:
            self.plugins = integrations.list_plugins()
        self.load_connectors()  # re-probe each page so status is never stale
        self.load_mcp_servers()

    # --------------------------------------------------------------- #
    #  Composer "+" menu
    # --------------------------------------------------------------- #
    def load_connectors(self):
        self.connectors = integrations.list_connectors()
        self.connectors_attention = sum(
            1 for c in self.connectors if c["status"] == "error")

    # ---- Connectors management page (/connectors) ----
    def load_connectors_page(self):
        self._load_recents()
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
    def load_mcp_servers(self):
        self.mcp_servers = integrations.list_mcp_servers()

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

    async def add_demo_mcp(self):
        """Register the bundled, secret-free demo MCP server (one click)."""
        self.mcp_status = "Connecting to demo MCP server…"
        yield
        item = await asyncio.to_thread(integrations.add_demo_mcp_server)
        self.load_mcp_servers()
        if item.get("status") == "connected":
            self.enabled_mcp = [*[x for x in self.enabled_mcp if x != item["id"]],
                                item["id"]]
            self.mcp_status = f"Connected · {item.get('detail', '')}"
        else:
            self.mcp_status = f"Failed: {item.get('detail', 'unknown error')}"
        yield

    async def save_mcp_server(self):
        cmd = self.mcp_command.strip()
        name = self.mcp_name.strip()
        if not (cmd and name):
            self.mcp_status = "Name and command are required."
            return
        args = [a for a in self.mcp_args.split() if a]
        self.mcp_status = f"Connecting to {name}…"
        yield
        item = await asyncio.to_thread(integrations.add_mcp_server, name, cmd, args)
        self.load_mcp_servers()
        if item.get("status") == "connected":
            self.enabled_mcp = [*[x for x in self.enabled_mcp if x != item["id"]],
                                item["id"]]
            self.mcp_add_open = False
            self.mcp_status = ""
        else:
            self.mcp_status = f"Failed: {item.get('detail', 'unknown error')}"
        yield

    def remove_mcp(self, sid: str):
        integrations.remove_mcp_server(sid)
        self.enabled_mcp = [x for x in self.enabled_mcp if x != sid]
        self.load_mcp_servers()

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

    def save_connector(self):
        if self.conn_name.strip() and self.conn_url.strip():
            integrations.add_connector(self.conn_name, self.conn_url,
                                       self.conn_hkey, self.conn_hval)
            self.conn_add_open = False
            self.load_connectors()

    def remove_user_connector(self, cid: str):
        integrations.remove_connector(cid)
        self.enabled_connectors = [x for x in self.enabled_connectors if x != cid]
        self.load_connectors()

    async def test_user_connector(self, cid: str):
        self.conn_test = f"Testing {cid}…"
        yield
        result = await asyncio.to_thread(integrations.test_connector, cid)
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
        if self.active_skill:
            chips.append(self.active_skill)
        return chips

    def select_model(self, m: str):
        self.model = m
        core.save_settings({"model": m, "effort": self.effort})

    def select_effort(self, level: str):
        self.effort = level
        core.save_settings({"model": self.model, "effort": level})

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
        pid = self.current_id or core.GENERAL_ID
        if not url:
            return
        self.github_status = "Importing…"
        yield
        count, err = await asyncio.to_thread(
            integrations.import_github_repo, url, pid)
        if err:
            self.github_status = f"Failed: {err}"
        else:
            self.github_status = f"Imported {count} file(s) into this project's KB."
            if pid != core.GENERAL_ID:
                self._refresh_files()
        yield

    # ---- Add files dialog ----
    def open_attach(self):
        self.attach_open = True

    def set_attach_open(self, value: bool):
        self.attach_open = value

    # --------------------------------------------------------------- #
    #  Customize (settings)
    # --------------------------------------------------------------- #
    def load_customize(self):
        self._load_recents()
        self.settings_saved = False

    def set_effort(self, v: str):
        self.effort = v
        core.save_settings({"model": self.model, "effort": v})

    def save_customize(self):
        core.save_settings({"model": self.model, "effort": self.effort})
        self.settings_saved = True

    def load_dashboard(self):
        self.projects = [
            core.project_card_view(p)
            for p in sorted(core.list_projects(),
                            key=lambda x: x.get("created_at", ""), reverse=True)
        ]
        self._load_recents()

    # --------------------------------------------------------------- #
    #  Chats dashboard (/chats) — all conversations across projects
    # --------------------------------------------------------------- #
    def load_chats(self):
        self.all_chats = core.list_all_conversations(limit=200)
        self._load_recents()

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

    def load_code(self):
        self._load_recents()
        self.section = "code"

    async def run_code(self, form_data: dict | None = None):
        sql = self.code_sql.strip()
        if not sql or self.code_running:
            return
        self.code_running = True
        self.code_md = ""
        self.code_info = "Running…"
        yield
        res = await asyncio.to_thread(core.execute_sql, sql, None)
        if res.get("ok"):
            self.code_md = _rows_to_markdown(res["columns"],
                                             res["rows"][:core.MAX_TABLE_ROWS_UI])
            self.code_info = (f"{res['total_rows']} rows · "
                              f"{core.fmt_bytes(res['bytes'])} scanned")
        else:
            self.code_md = ""
            self.code_info = res.get("agent_text", res.get("error", "Failed"))
        self.code_running = False
        yield

    # ---- Artifacts ----
    def load_artifacts(self):
        self.all_files = core.list_all_files()
        self._load_recents()

    @rx.var
    def has_artifacts(self) -> bool:
        return len(self.all_files) > 0

    # ---- Cowork / New chat (General space) ----
    def load_cowork(self):
        self._load_project_context(core.GENERAL_ID)
        self.conversations = core.list_conversations(core.GENERAL_ID)
        self._load_recents()
        self.messages = []
        self.current_conv_id = ""
        self.conv_title = ""
        self.chat_input = ""
        self.is_running = False
        self.section = "cowork"

    def new_chat(self):
        return rx.redirect("/cowork")

    # ---- Pin / Change project / Remove from project ----
    def toggle_pin(self):
        if self.current_id and self.current_conv_id:
            self.conv_pinned = not self.conv_pinned
            core.set_conversation_pinned(self.current_id, self.current_conv_id,
                                         self.conv_pinned)
            self._load_recents()

    def open_change_project(self):
        self.change_open = True

    def set_change_open(self, value: bool):
        self.change_open = value

    @rx.var
    def move_targets(self) -> list[dict]:
        """Projects (+ General) the current conversation can move to."""
        targets = [{"id": core.GENERAL_ID, "name": core.GENERAL_NAME}]
        targets += [{"id": p["id"], "name": p["name"]} for p in core.list_projects()]
        return [t for t in targets if t["id"] != self.current_id]

    def move_to_project(self, dst_pid: str):
        src, cid = self.current_id, self.current_conv_id
        self.change_open = False
        if not dst_pid:
            return
        if cid:
            # Existing conversation → move the file and follow it.
            core.move_conversation(src, cid, dst_pid)
            return rx.redirect(f"/project/{dst_pid}/c/{cid}")
        # New-chat composer (no conversation yet): carry the typed draft into a
        # new conversation in the destination, else just open that workspace.
        text = self.chat_input.strip()
        if text:
            conv = core.create_conversation(dst_pid, text)
            self.chat_input = ""
            return rx.redirect(f"/project/{dst_pid}/c/{conv['id']}")
        return rx.redirect(f"/project/{dst_pid}")

    def remove_from_project(self):
        src, cid = self.current_id, self.current_conv_id
        if src and cid and src != core.GENERAL_ID:
            core.move_conversation(src, cid, core.GENERAL_ID)
        return rx.redirect(f"/project/{core.GENERAL_ID}/c/{cid}")

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

    def bulk_delete(self):
        sel = set(self.selected_ids)
        for c in self.all_chats:
            if c["id"] in sel:
                core.delete_conversation(c["project_id"], c["id"])
        self.selected_ids = []
        self.select_mode = False
        self.all_chats = core.list_all_conversations(limit=200)
        self._load_recents()

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

    def create_project(self):
        name = self.new_name.strip()
        if not name:
            return
        meta = core.create_project(name)
        if self.new_desc.strip():
            core.save_project_instructions(meta["id"], self.new_desc.strip())
        self.show_new_dialog = False
        self.load_dashboard()
        return rx.redirect(f"/project/{meta['id']}")

    def open_project(self, pid: str):
        self.current_id = pid
        return rx.redirect(f"/project/{pid}")

    def delete_current_project(self):
        if self.current_id:
            core.delete_project(self.current_id)
        return rx.redirect("/")

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
        if self.current_id == core.GENERAL_ID:
            return "/cowork"
        return f"/project/{self.current_id}"

    @rx.var
    def is_general(self) -> bool:
        return self.current_id == core.GENERAL_ID

    def _load_project_context(self, pid: str) -> dict | None:
        if pid == core.GENERAL_ID:
            self.current_id = pid
            self.current_name = core.GENERAL_NAME
            self.instructions = ""
            self.instructions_draft = ""
            self.editing_instructions = False
            self.memory_text, self.memory_updated = "", ""
            self.files = []
            self.cap_used, self.cap_pct = 0.0, 0
            return {"id": pid, "name": core.GENERAL_NAME}
        proj = core.get_project(pid)
        if not proj:
            return None
        self.current_id = pid
        self.current_name = proj.get("name", "Untitled")
        self.instructions = core.get_project_instructions(pid)
        self.instructions_draft = self.instructions
        self.editing_instructions = False
        self.memory_text, self.memory_updated = core.get_project_memory(pid)
        self._refresh_files()
        return proj

    def load_workspace(self):
        self.load_dashboard()  # populate the sidebar project list on deep-links too
        pid = self._pid()
        if not self._load_project_context(pid):
            return rx.redirect("/")
        self.conversations = core.list_conversations(pid)
        self._load_recents()
        self.messages = []
        self.current_conv_id = ""
        self.conv_title = ""
        self.chat_input = ""
        self.is_running = False

    def _refresh_files(self):
        self.files = core.list_project_files(self.current_id)
        cap = core.project_capacity(self.current_id)
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

    def save_instructions(self):
        core.save_project_instructions(self.current_id, self.instructions_draft)
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
    def start_conversation(self, form_data: dict | None = None):
        text = self.chat_input.strip()
        if not text or self.is_running or not self.current_id:
            return
        conv = core.create_conversation(self.current_id, text)
        self.chat_input = ""
        return rx.redirect(f"/project/{self.current_id}/c/{conv['id']}")

    # --- Conversation page on_load: render it, run agent if a turn is pending --- #
    async def load_conversation(self):
        self.load_dashboard()
        pid = self._pid()
        if not self._load_project_context(pid):
            yield rx.redirect("/")
            return
        cid = self._cid()
        conv = core.get_conversation(pid, cid)
        if not conv:
            yield rx.redirect(f"/project/{pid}")
            return
        self.current_conv_id = cid
        self.conv_title = conv.get("title", "Conversation")
        self.conv_pinned = bool(conv.get("pinned", False))
        self.messages = self._normalize_messages(conv.get("messages", []))
        self.expanded_thoughts = set()
        self.expanded_sources = set()
        self.expanded_tools = set()
        self.chat_input = ""
        self.is_running = False
        self._load_recents()
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
        core.save_conversation(self.current_id, self.current_conv_id, self.messages,
                               self.conv_title or None)
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
                m["content"] = agent._strip_answer_label(m["content"])
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

    # --- Shared agent runner: stream events into the transcript, then persist --- #
    async def _run_agent(self, goal: str, pid: str, cid: str, first_turn: bool = False):
        self.is_running = True
        yield
        history = self._chat_history()
        proj_instr = core.get_project_instructions(pid) if pid else ""
        # Active skill: manual selection, else an auto-trigger match on the goal.
        skill_name = self.active_skill or integrations.matching_skill(goal)
        skill_instr = ""
        if skill_name:
            sk = integrations.get_skill(skill_name)
            skill_instr = sk["instructions"] if sk else ""
        extra_tools = integrations.agent_tools(list(self.enabled_plugins),
                                               list(self.enabled_connectors),
                                               list(self.enabled_mcp))
        try:
            async for ev in agent.run_turn(goal, history, pid or None, self.model,
                                           proj_instr, effort=self.effort,
                                           web_search=self.web_search_on,
                                           skill_instructions=skill_instr,
                                           research=self.research_on,
                                           extra_tools=extra_tools,
                                           web_fetch=self.web_fetch_on,
                                           code_exec=self.code_exec_on,
                                           bash=self.bash_on,
                                           text_editor=self.text_editor_on,
                                           memory=self.memory_on):
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
                    cap = f"**{ev['total']} rows · {core.fmt_bytes(ev['bytes'])} scanned**"
                    md = _rows_to_markdown(ev["columns"], ev["rows"])
                    self.messages.append({"role": "tool", "content": f"{cap}\n\n{md}",
                                          "kind": "table"})
                elif t == "final":
                    self._close_thinking(int(ev.get("verify_elapsed", 0) or 0))
                    self.messages.append({"role": "assistant", "content": ev["text"],
                                          "kind": "final"})
                elif t == "error":
                    self._close_thinking()
                    self.messages.append({"role": "assistant", "content": ev["text"],
                                          "kind": "error"})
                yield
        except Exception as e:
            self.messages.append({"role": "assistant", "content": f"Agent error: {e}",
                                  "kind": "error"})
        self.is_running = False
        core.save_conversation(pid, cid, self.messages, self.conv_title or None)
        yield
        # Give a freshly-created conversation a concise Claude-style title.
        if first_turn and pid and cid:
            try:
                title = await asyncio.to_thread(core.generate_conversation_title, goal)
                if title:
                    self.conv_title = title
                    core.set_conversation_title(pid, cid, title)
                    yield
            except Exception:
                pass

    def delete_current_conversation(self):
        pid = self.current_id
        if pid and self.current_conv_id:
            core.delete_conversation(pid, self.current_conv_id)
        return rx.redirect(f"/project/{pid}")

    # --- Rename current conversation (breadcrumb menu) --- #
    def open_rename(self):
        self.rename_draft = self.conv_title
        self.rename_open = True

    def set_rename_open(self, value: bool):
        self.rename_open = value

    def set_rename_draft(self, v: str):
        self.rename_draft = v

    def save_rename(self):
        title = self.rename_draft.strip()
        if title and self.current_id and self.current_conv_id:
            core.set_conversation_title(self.current_id, self.current_conv_id, title)
            self.conv_title = title
            self._load_recents()
        self.rename_open = False

    async def handle_upload(self, files: list[rx.UploadFile]):
        self.uploading = True
        yield
        ok, failed = 0, []
        for f in files:
            name = getattr(f, "name", None) or getattr(f, "filename", "upload.bin")
            try:
                data = await f.read()
                dest = core.save_uploaded_file(self.current_id, name, data)
                core.ingest_file_to_kb(self.current_id, dest)
                ok += 1
            except Exception as e:
                failed.append(f"{name}: {e}")
        self._refresh_files()
        self.all_files = core.list_all_files()   # keep /artifacts in sync
        self.uploading = False
        if failed:
            self.attach_status = (f"Uploaded {ok}; {len(failed)} failed: "
                                  f"{'; '.join(failed)[:160]}")
        else:
            self.attach_status = ""
            self.attach_open = False             # close only on full success
        yield
