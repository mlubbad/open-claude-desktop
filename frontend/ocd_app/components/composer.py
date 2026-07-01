"""Composer — identical to Claude's input bar (+ menu, model pill, send)."""
import reflex as rx

from ..state import AppState
from .theme import BORDER, CARD_BG


def _move_target_item(t: rx.Var) -> rx.Component:
    return rx.menu.item(rx.icon("folder", size=14), t["name"],
                        on_click=AppState.move_to_project(t["id"]))


def _skill_item(s: rx.Var) -> rx.Component:
    return rx.menu.item(
        rx.cond(AppState.active_skill == s["name"],
                rx.icon("check", size=13), rx.box(width="13px")),
        rx.text(s["name"], size="2"),
        on_click=AppState.apply_skill(s["name"]),
    )


def _builtin_tool_item(icon: str, label: str, flag, handler,
                       warn: bool = False) -> rx.Component:
    """A togglable built-in tool row (Claude-style) in the composer Tools menu."""
    return rx.menu.item(
        rx.icon(icon, size=15),
        rx.text(label, size="2"),
        rx.cond(warn, rx.icon("triangle-alert", size=12, color="var(--amber-9)"),
                rx.fragment()),
        rx.spacer(),
        rx.cond(flag, rx.icon("check", size=14, color="var(--accent-9)"), rx.fragment()),
        on_click=handler,
    )


def _plugin_item(p: rx.Var) -> rx.Component:
    return rx.menu.item(
        rx.cond(AppState.enabled_plugins.contains(p["name"]),
                rx.icon("check", size=13), rx.box(width="13px")),
        rx.text(p["name"], size="2"),
        on_click=AppState.toggle_plugin(p["name"]),
    )


def _connector_item(c: rx.Var) -> rx.Component:
    return rx.menu.item(
        rx.cond(
            c["type"] == "rest",
            rx.cond(AppState.enabled_connectors.contains(c["id"]),
                    rx.icon("check", size=13, color="var(--accent-9)"),
                    rx.box(width="13px")),
            rx.icon("circle", size=8,
                    color=rx.cond(c["status"] == "error", "var(--red-9)",
                                  "var(--green-9)")),
        ),
        rx.text(c["name"], size="2"),
        rx.spacer(),
        rx.text(c["detail"], size="1", color="var(--gray-9)", no_of_lines=1),
        on_click=AppState.toggle_connector(c["id"]),
    )


def _mcp_item(s: rx.Var) -> rx.Component:
    return rx.menu.item(
        rx.cond(AppState.enabled_mcp.contains(s["id"]),
                rx.icon("check", size=13, color="var(--accent-9)"),
                rx.cond(s["status"] == "error",
                        rx.icon("circle-alert", size=12, color="var(--red-9)"),
                        rx.box(width="13px"))),
        rx.text(s["name"], size="2"),
        rx.spacer(),
        rx.text(s["detail"], size="1", color="var(--gray-9)", no_of_lines=1),
        on_click=AppState.toggle_mcp(s["id"]),
    )


def plus_menu() -> rx.Component:
    return rx.menu.root(
        rx.menu.trigger(
            rx.box(rx.icon("plus", size=18, color="var(--gray-9)"),
                   width="32px", height="32px", border_radius="8px",
                   display="flex", align_items="center", justify_content="center",
                   cursor="pointer", _hover={"background": "var(--gray-3)"}),
        ),
        rx.menu.content(
            rx.menu.item(rx.icon("paperclip", size=15), "Add files or photos",
                         on_click=AppState.open_attach),
            rx.menu.sub(
                rx.menu.sub_trigger(rx.icon("folder", size=15), "Add to project"),
                rx.menu.sub_content(
                    rx.foreach(AppState.move_targets, _move_target_item)),
            ),
            rx.menu.item(rx.icon("git-branch", size=15), "Add from GitHub",
                         on_click=AppState.open_github),
            rx.menu.separator(),
            rx.menu.sub(
                rx.menu.sub_trigger(rx.icon("sparkles", size=15), "Skills"),
                rx.menu.sub_content(rx.foreach(AppState.skills, _skill_item)),
            ),
            rx.menu.sub(
                rx.menu.sub_trigger(
                    rx.icon("blocks", size=15), "Connectors", rx.spacer(),
                    rx.cond(AppState.connectors_attention > 0,
                            rx.badge(AppState.connectors_attention,
                                     color_scheme="amber", size="1"),
                            rx.fragment()),
                ),
                rx.menu.sub_content(
                    rx.foreach(AppState.connectors, _connector_item),
                    rx.menu.separator(),
                    rx.menu.item("MCP servers", disabled=True),
                    rx.foreach(AppState.mcp_servers, _mcp_item),
                    rx.menu.item(rx.icon("plug", size=14), "Add demo MCP server",
                                 on_click=AppState.add_demo_mcp),
                    rx.menu.item(rx.icon("plus", size=14), "Add MCP server…",
                                 on_click=AppState.open_add_mcp),
                    rx.menu.separator(),
                    rx.menu.item(rx.icon("settings", size=14), "Manage connectors…",
                                 on_click=rx.redirect("/connectors")),
                ),
            ),
            rx.menu.sub(
                rx.menu.sub_trigger(rx.icon("puzzle", size=15), "Plugins"),
                rx.menu.sub_content(rx.foreach(AppState.plugins, _plugin_item)),
            ),
            rx.menu.sub(
                rx.menu.sub_trigger(rx.icon("wrench", size=15), "Tools"),
                rx.menu.sub_content(
                    _builtin_tool_item("database", "BigQuery (AJ360)",
                                       AppState.bigquery_on, AppState.toggle_bigquery),
                    _builtin_tool_item("link", "Web fetch", AppState.web_fetch_on,
                                       AppState.toggle_web_fetch),
                    _builtin_tool_item("brain", "Memory", AppState.memory_on,
                                       AppState.toggle_memory),
                    _builtin_tool_item("file-pen", "Text editor", AppState.text_editor_on,
                                       AppState.toggle_text_editor),
                    rx.menu.separator(),
                    rx.menu.item("Sandboxed · enable with care", disabled=True),
                    _builtin_tool_item("square-terminal", "Code execution",
                                       AppState.code_exec_on, AppState.toggle_code_exec,
                                       warn=True),
                    _builtin_tool_item("terminal", "Bash", AppState.bash_on,
                                       AppState.toggle_bash, warn=True),
                ),
            ),
            rx.menu.separator(),
            rx.menu.item(rx.icon("telescope", size=15), "Research", rx.spacer(),
                         rx.cond(AppState.research_on, rx.icon("check", size=14),
                                 rx.fragment()),
                         on_click=AppState.toggle_research),
            rx.menu.item(rx.icon("globe", size=15), "Web search", rx.spacer(),
                         rx.cond(AppState.web_search_on, rx.icon("check", size=14),
                                 rx.fragment()),
                         on_click=AppState.toggle_web_search),
        ),
    )


def _model_menu_item(m: rx.Var) -> rx.Component:
    return rx.menu.item(
        rx.cond(AppState.model == m, rx.icon("check", size=13), rx.box(width="13px")),
        m, on_click=AppState.select_model(m),
    )


def _effort_menu_item(e: rx.Var) -> rx.Component:
    return rx.menu.item(
        rx.cond(AppState.effort == e, rx.icon("check", size=13), rx.box(width="13px")),
        rx.vstack(
            rx.text(e, size="2"),
            rx.text(AppState.effort_descriptions[e], size="1", color="var(--gray-9)"),
            spacing="0", align="start",
        ),
        on_click=AppState.select_effort(e),
    )


def model_pill() -> rx.Component:
    return rx.menu.root(
        rx.menu.trigger(
            rx.hstack(
                rx.text(AppState.model, size="1", color="var(--gray-11)"),
                rx.text(AppState.effort, size="1", color="var(--gray-9)"),
                rx.icon("chevron-down", size=12, color="var(--gray-9)"),
                spacing="1", align="center", cursor="pointer",
                padding="3px 6px", border_radius="6px",
                _hover={"background": "var(--gray-3)"},
            ),
        ),
        rx.menu.content(
            rx.menu.item("Model", disabled=True),
            rx.foreach(AppState.model_options, _model_menu_item),
            rx.menu.separator(),
            rx.menu.item("Extended thinking", disabled=True),
            rx.foreach(AppState.effort_levels, _effort_menu_item),
        ),
    )


def github_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Add from GitHub"),
            rx.dialog.description("Import a public repo's text files into this "
                                 "project's knowledge base.", size="2",
                                 color="var(--gray-10)"),
            rx.input(placeholder="https://github.com/owner/repo",
                     value=AppState.github_url, on_change=AppState.set_github_url,
                     width="100%", margin_y="12px"),
            rx.hstack(
                rx.dialog.close(
                    rx.button("Close", variant="soft", color_scheme="gray", type="button",
                              on_click=lambda: AppState.set_github_open(False))),
                rx.button("Import", type="button", on_click=AppState.run_github_import),
                spacing="3", justify="end",
            ),
            rx.cond(AppState.github_status != "",
                    rx.text(AppState.github_status, size="1", color="var(--gray-10)",
                            margin_top="10px")),
            max_width="460px",
        ),
        open=AppState.github_open, on_open_change=AppState.set_github_open,
    )


def attach_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Add files"),
            rx.dialog.description("Upload files into this project's knowledge base.",
                                 size="2", color="var(--gray-10)"),
            rx.upload(
                rx.vstack(
                    rx.icon("upload", size=22, color="var(--gray-9)"),
                    rx.text("Drop files here or click to browse", size="2",
                            color="var(--gray-9)"),
                    align="center", spacing="2",
                ),
                id="composer_upload", border="1px dashed var(--gray-6)",
                border_radius="10px", padding="28px", width="100%", margin_y="12px",
            ),
            rx.hstack(
                rx.dialog.close(
                    rx.button("Close", variant="soft", color_scheme="gray", type="button",
                              on_click=lambda: AppState.set_attach_open(False))),
                rx.button("Upload", type="button",
                          on_click=AppState.handle_upload(
                              rx.upload_files(upload_id="composer_upload"))),
                rx.cond(AppState.uploading,
                        rx.text("Uploading…", size="1", color="var(--accent-9)")),
                spacing="3", justify="end", align="center",
            ),
            rx.cond(AppState.attach_status != "",
                    rx.text(AppState.attach_status, size="1", color="var(--red-11)",
                            margin_top="8px")),
            max_width="460px",
        ),
        open=AppState.attach_open, on_open_change=AppState.set_attach_open,
    )


def mcp_add_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Add MCP server"),
            rx.dialog.description(
                "Connect a Model Context Protocol server (stdio). Its tools become "
                "available to the agent — the same mechanism Claude Desktop connectors "
                "use.", size="2", color="var(--gray-10)"),
            rx.vstack(
                rx.input(placeholder="Name (e.g. Filesystem)", value=AppState.mcp_name,
                         on_change=AppState.set_mcp_name, width="100%"),
                rx.input(placeholder="Command (e.g. npx or python)",
                         value=AppState.mcp_command,
                         on_change=AppState.set_mcp_command, width="100%"),
                rx.input(placeholder="Args (space-separated, e.g. -y server-name)",
                         value=AppState.mcp_args, on_change=AppState.set_mcp_args,
                         width="100%"),
                spacing="2", width="100%", margin_y="12px",
            ),
            rx.hstack(
                rx.dialog.close(
                    rx.button("Close", variant="soft", color_scheme="gray", type="button",
                              on_click=lambda: AppState.set_mcp_add_open(False))),
                rx.button("Connect", type="button", on_click=AppState.save_mcp_server),
                spacing="3", justify="end",
            ),
            rx.cond(AppState.mcp_status != "",
                    rx.text(AppState.mcp_status, size="1", color="var(--gray-10)",
                            margin_top="10px")),
            max_width="460px",
        ),
        open=AppState.mcp_add_open, on_open_change=AppState.set_mcp_add_open,
    )


def _mode_chip(label: rx.Var) -> rx.Component:
    return rx.badge(label, size="1", variant="soft", color_scheme="bronze")


def composer(on_submit, placeholder: str) -> rx.Component:
    return rx.box(
        rx.form(
            rx.box(
                rx.text_area(
                    value=AppState.chat_input, on_change=AppState.set_chat_input,
                    placeholder=placeholder, name="msg", rows="2",
                    enter_key_submit=True, resize="none", width="100%",
                    style={"background": "transparent", "boxShadow": "none",
                           "border": "none", "outline": "none"},
                ),
                rx.hstack(
                    plus_menu(),
                    rx.foreach(AppState.active_modes, _mode_chip),
                    rx.spacer(),
                    model_pill(),
                    rx.tooltip(
                        rx.icon("mic", size=17, color="var(--gray-8)",
                                opacity="0.4", cursor="not-allowed"),
                        content="Voice input — coming soon"),
                    rx.tooltip(
                        rx.icon("audio-lines", size=17, color="var(--gray-8)",
                                opacity="0.4", cursor="not-allowed"),
                        content="Dictation — coming soon"),
                    rx.button(rx.icon("arrow-up", size=16), type="submit",
                              radius="full", disabled=~AppState.can_send),
                    width="100%", align="center", margin_top="6px", spacing="3",
                ),
                padding="12px 14px", border=BORDER, border_radius="16px",
                background=CARD_BG, box_shadow="var(--shadow-2)",
            ),
            on_submit=on_submit, reset_on_submit=False, width="100%",
        ),
        github_dialog(),
        attach_dialog(),
        mcp_add_dialog(),
        width="100%",
    )


def workspace_composer() -> rx.Component:
    return composer(AppState.start_conversation, "How can I help you today?")
