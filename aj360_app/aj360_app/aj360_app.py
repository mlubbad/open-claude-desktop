"""AJ360 — Projects UI built in Reflex (Claude-Desktop-style workspace)."""
import reflex as rx

from .state import AppState

# --------------------------------------------------------------------------- #
#  Design tokens
# --------------------------------------------------------------------------- #
BORDER = "1px solid var(--gray-4)"
CARD_BG = "var(--color-background)"
PAGE_BG = "var(--gray-1)"


# --------------------------------------------------------------------------- #
#  Sidebar (shared shell) — Claude-style. Unimplemented items are disabled.
# --------------------------------------------------------------------------- #
def _tab(icon: str, label: str, href: str, key: str) -> rx.Component:
    active = AppState.section == key
    return rx.link(
        rx.hstack(
            rx.icon(icon, size=15), rx.text(label, size="2", weight="medium"),
            spacing="1", align="center", justify="center", width="100%",
            padding="6px 8px", border_radius="8px",
            background=rx.cond(active, CARD_BG, "transparent"),
            color=rx.cond(active, "var(--gray-12)", "var(--gray-9)"),
            box_shadow=rx.cond(active, "var(--shadow-2)", "none"),
            opacity=rx.cond(active, "1", "0.7"),
        ),
        href=href, flex="1", underline="none",
    )


def top_tabs() -> rx.Component:
    return rx.hstack(
        _tab("message-square", "Chat", "/", "chat"),
        _tab("arrow-left-right", "Cowork", "/cowork", "cowork"),
        _tab("code", "Code", "/code", "code"),
        spacing="1", padding="3px", background="var(--gray-3)",
        border_radius="10px", width="100%",
    )


def nav_item(icon: str, label: str, href: str = "", disabled: bool = False) -> rx.Component:
    row = rx.box(
        rx.hstack(
            rx.icon(icon, size=17, color="var(--gray-9)"),
            rx.text(label, size="2", color="var(--gray-12)"),
            spacing="3", align="center", width="100%",
        ),
        width="100%", padding="7px 10px", border_radius="8px",
        _hover=({} if disabled else {"background": "var(--gray-3)"}),
    )
    if disabled:
        return rx.box(row, width="100%", opacity="0.4", cursor="not-allowed",
                      title="Coming soon")
    return rx.link(row, href=href, width="100%", underline="none")


def sidebar_recent(c: rx.Var) -> rx.Component:
    return rx.link(
        rx.text(c["title"], size="2", no_of_lines=1, color="var(--gray-11)"),
        href=c["href"], width="100%", underline="none",
        padding="5px 8px", border_radius="6px",
        _hover={"background": "var(--gray-3)"},
    )


def user_footer() -> rx.Component:
    return rx.hstack(
        rx.box(rx.text("ML", size="1", weight="bold", color="var(--gray-1)"),
               width="26px", height="26px", border_radius="50%",
               background="var(--gray-9)", display="flex",
               align_items="center", justify_content="center"),
        rx.text("Mohammed", size="2", color="var(--gray-12)"),
        rx.text("· Max", size="1", color="var(--gray-9)"),
        rx.spacer(),
        rx.icon("chevron-down", size=14, color="var(--gray-9)"),
        spacing="2", align="center", width="100%", padding="8px 6px",
        opacity="0.85", cursor="default",
    )


def sidebar() -> rx.Component:
    return rx.vstack(
        top_tabs(),
        rx.vstack(
            nav_item("plus", "New chat", href="/cowork"),
            nav_item("folder", "Projects", href="/"),
            nav_item("blocks", "Artifacts", href="/artifacts"),
            nav_item("sliders-horizontal", "Customize", href="/customize"),
            spacing="0", width="100%", margin_top="6px",
        ),
        rx.hstack(
            rx.text("Recents", size="1", weight="medium", color="var(--gray-9)"),
            rx.spacer(),
            rx.link(rx.text("View all", size="1", color="var(--gray-9)"),
                    href="/chats", underline="none"),
            width="100%", align="center", margin_top="14px", padding_x="8px",
        ),
        rx.scroll_area(
            rx.vstack(rx.foreach(AppState.recents, sidebar_recent),
                      spacing="0", width="100%"),
            scrollbars="vertical", flex="1", width="100%", margin_top="4px",
        ),
        rx.divider(),
        user_footer(),
        width="270px", height="100vh", padding="14px 12px",
        border_right=BORDER, background=PAGE_BG, spacing="2",
        position="sticky", top="0",
    )


# --------------------------------------------------------------------------- #
#  Dashboard
# --------------------------------------------------------------------------- #
def project_card(p: rx.Var) -> rx.Component:
    return rx.box(
        rx.heading(p["name"], size="4", weight="medium", color="var(--gray-12)"),
        rx.text("Updated ", p["updated"], size="1", color="var(--gray-9)",
                margin_top="4px", margin_bottom="10px"),
        rx.text(p["desc"], size="2", color="var(--gray-11)", line_height="1.4"),
        on_click=AppState.open_project(p["id"]),
        cursor="pointer", padding="16px", border=BORDER, border_radius="12px",
        background=CARD_BG, min_height="120px",
        transition="border-color .15s, box-shadow .15s",
        _hover={"border_color": "var(--gray-8)",
                "box_shadow": "var(--shadow-3)"},
    )


def new_project_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("New project"),
            rx.dialog.description("Name it and (optionally) describe its goal.",
                                  size="2", color="var(--gray-10)"),
            rx.vstack(
                rx.input(placeholder="Project name", value=AppState.new_name,
                         on_change=AppState.set_new_name, width="100%"),
                rx.text_area(placeholder="Describe the project, goals, subject…",
                             value=AppState.new_desc, on_change=AppState.set_new_desc,
                             width="100%", rows="4"),
                spacing="3", margin_y="14px", width="100%",
            ),
            rx.hstack(
                rx.dialog.close(
                    rx.button("Cancel", variant="soft", color_scheme="gray",
                              on_click=lambda: AppState.set_new_dialog(False))),
                rx.button("Create project", on_click=AppState.create_project),
                spacing="3", justify="end",
            ),
            max_width="460px",
        ),
        open=AppState.show_new_dialog,
        on_open_change=AppState.set_new_dialog,
    )


def dashboard() -> rx.Component:
    return rx.hstack(
        sidebar(),
        rx.box(
            rx.hstack(
                rx.heading("Projects", size="7", weight="bold"),
                rx.spacer(),
                rx.button("Sort by Last updated", rx.icon("chevron-down", size=14),
                          variant="soft", color_scheme="gray", disabled=True),
                rx.button(rx.icon("plus", size=16), "New project",
                          on_click=AppState.open_new_dialog),
                width="100%", align="center", margin_bottom="18px", spacing="3",
            ),
            rx.input(
                rx.input.slot(rx.icon("search", size=15)),
                placeholder="Search projects…", value=AppState.search,
                on_change=AppState.set_search, width="100%", size="3",
                margin_bottom="22px",
            ),
            rx.cond(
                AppState.has_projects,
                rx.box(
                    rx.foreach(AppState.filtered_projects, project_card),
                    display="grid",
                    grid_template_columns="repeat(auto-fill, minmax(240px, 1fr))",
                    gap="16px", width="100%",
                ),
                rx.box(
                    rx.text("No projects yet. Click “New project” to create one.",
                            color="var(--gray-9)"),
                    padding="40px", border="1px dashed var(--gray-6)",
                    border_radius="12px", text_align="center",
                ),
            ),
            new_project_dialog(),
            flex="1", padding="32px 40px", height="100vh",
            overflow_y="auto", background=CARD_BG,
        ),
        spacing="0", width="100%", align="start",
    )


# --------------------------------------------------------------------------- #
#  Chats dashboard  (/chats) — all conversations across projects
# --------------------------------------------------------------------------- #
def chat_row(c: rx.Var) -> rx.Component:
    body = rx.hstack(
        rx.cond(
            AppState.select_mode,
            rx.checkbox(checked=AppState.selected_ids.contains(c["id"])),
            rx.fragment(),
        ),
        rx.text(c["title"], size="3", color="var(--gray-12)", no_of_lines=1, flex="1"),
        rx.text(c["project_name"], size="1", color="var(--gray-9)"),
        rx.text(c["updated_rel"], size="1", color="var(--gray-9)",
                width="120px", text_align="right"),
        spacing="4", align="center", width="100%",
    )
    return rx.cond(
        AppState.select_mode,
        rx.box(body, on_click=AppState.toggle_selected(c["id"]), cursor="pointer",
               width="100%", padding="15px 8px", border_bottom=BORDER,
               _hover={"background": "var(--gray-2)"}),
        rx.link(body, href=c["href"], width="100%", underline="none",
                padding="15px 8px", border_bottom=BORDER,
                _hover={"background": "var(--gray-2)"}),
    )


def chats_dashboard() -> rx.Component:
    return rx.hstack(
        sidebar(),
        rx.box(
            rx.hstack(
                rx.heading("Chats", size="7", weight="bold"),
                rx.spacer(),
                rx.select(AppState.project_filter_options, value=AppState.chats_filter,
                          on_change=AppState.set_chats_filter, width="180px"),
                rx.cond(
                    AppState.select_mode,
                    rx.button(rx.icon("trash-2", size=14), "Delete (",
                              AppState.selected_count, ")", color_scheme="red",
                              on_click=AppState.bulk_delete,
                              disabled=AppState.selected_count == 0),
                    rx.fragment(),
                ),
                rx.button(rx.cond(AppState.select_mode, "Done", "Select chats"),
                          variant="soft", color_scheme="gray",
                          on_click=AppState.toggle_select_mode),
                rx.button("New chat", on_click=AppState.new_chat),
                width="100%", align="center", margin_bottom="20px", spacing="3",
            ),
            rx.input(
                rx.input.slot(rx.icon("search", size=15)),
                placeholder="Search chats…", value=AppState.chats_search,
                on_change=AppState.set_chats_search, width="100%", size="3",
                margin_bottom="10px",
            ),
            rx.cond(
                AppState.has_chats,
                rx.vstack(rx.foreach(AppState.filtered_chats, chat_row),
                          spacing="0", width="100%"),
                rx.box(rx.text("No chats yet. Open a project and ask something.",
                               color="var(--gray-9)"),
                       padding="40px", text_align="center"),
            ),
            flex="1", padding="32px 40px", height="100vh",
            overflow_y="auto", background=CARD_BG,
        ),
        spacing="0", width="100%", align="start",
    )


# --------------------------------------------------------------------------- #
#  Customize  (/customize) — settings
# --------------------------------------------------------------------------- #
def _setting_row(title: str, desc: str, control: rx.Component) -> rx.Component:
    return rx.hstack(
        rx.vstack(
            rx.text(title, size="3", weight="medium", color="var(--gray-12)"),
            rx.text(desc, size="1", color="var(--gray-9)"),
            spacing="1", align="start",
        ),
        rx.spacer(),
        control,
        width="100%", align="center", padding="18px 0", border_bottom=BORDER,
    )


def customize_page() -> rx.Component:
    return rx.hstack(
        sidebar(),
        rx.box(
            rx.heading("Customize", size="7", weight="bold", margin_bottom="4px"),
            rx.text("Defaults applied to the BigQuery agent.", size="2",
                    color="var(--gray-9)", margin_bottom="22px"),
            rx.box(
                _setting_row(
                    "Agent model", "Model the agent uses by default.",
                    rx.select(AppState.model_options, value=AppState.model,
                              on_change=AppState.set_model, width="220px")),
                _setting_row(
                    "Extended thinking", "Reasoning depth: Low/Medium are direct; High "
                    "adds a planning pass; Max also self-verifies the answer.",
                    rx.select(AppState.effort_levels, value=AppState.effort,
                              on_change=AppState.set_effort, width="160px")),
                _setting_row(
                    "Appearance", "Switch between light and dark theme.",
                    rx.color_mode.button()),
                width="100%", max_width="760px",
            ),
            rx.hstack(
                rx.button("Save changes", on_click=AppState.save_customize),
                rx.cond(AppState.settings_saved,
                        rx.text("Saved ✓", size="2", color="var(--green-11)")),
                spacing="3", align="center", margin_top="20px",
            ),
            flex="1", padding="32px 40px", height="100vh",
            overflow_y="auto", background=CARD_BG,
        ),
        spacing="0", width="100%", align="start",
    )


# --------------------------------------------------------------------------- #
#  Code  (/code) — read-only SQL console
# --------------------------------------------------------------------------- #
def code_page() -> rx.Component:
    return rx.hstack(
        sidebar(),
        rx.box(
            rx.heading("Code", size="7", weight="bold", margin_bottom="2px"),
            rx.text("Run read-only BigQuery SQL directly (SELECT only).", size="2",
                    color="var(--gray-9)", margin_bottom="16px"),
            rx.form(
                rx.text_area(value=AppState.code_sql, on_change=AppState.set_code_sql,
                             placeholder="SELECT … FROM `project.dataset.table` LIMIT 100",
                             rows="8", width="100%",
                             style={"fontFamily": "var(--code-font-family)"}),
                rx.hstack(
                    rx.button(rx.icon("play", size=15), "Run", type="submit",
                              disabled=AppState.code_running),
                    rx.text(AppState.code_info, size="1", color="var(--gray-9)"),
                    spacing="3", align="center", margin_top="10px",
                ),
                on_submit=AppState.run_code, reset_on_submit=False, width="100%",
            ),
            rx.cond(
                AppState.code_md != "",
                rx.box(rx.markdown(AppState.code_md), border=BORDER,
                       border_radius="10px", padding="6px 14px", margin_top="16px",
                       overflow_x="auto", background=CARD_BG),
            ),
            flex="1", padding="32px 40px", height="100vh",
            overflow_y="auto", background=CARD_BG,
        ),
        spacing="0", width="100%", align="start",
    )


# --------------------------------------------------------------------------- #
#  Artifacts  (/artifacts) — global files library
# --------------------------------------------------------------------------- #
def artifact_card(f: rx.Var) -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.icon("file-text", size=16, color="var(--gray-9)"),
            rx.badge(f["badge"], size="1", variant="soft", color_scheme="gray"),
            rx.spacer(),
            rx.text(f["meta"], size="1", color="var(--gray-9)"),
            width="100%", align="center",
        ),
        rx.text(f["name"], size="2", weight="medium", color="var(--gray-12)",
                no_of_lines=2, margin_top="10px"),
        rx.text(f["project_name"], size="1", color="var(--gray-9)", margin_top="6px"),
        padding="14px", border=BORDER, border_radius="12px", background=CARD_BG,
        min_height="112px",
    )


def artifacts_page() -> rx.Component:
    return rx.hstack(
        sidebar(),
        rx.box(
            rx.heading("Artifacts", size="7", weight="bold", margin_bottom="2px"),
            rx.text("Files across all your projects.", size="2",
                    color="var(--gray-9)", margin_bottom="20px"),
            rx.cond(
                AppState.has_artifacts,
                rx.box(
                    rx.foreach(AppState.all_files, artifact_card),
                    display="grid",
                    grid_template_columns="repeat(auto-fill, minmax(240px, 1fr))",
                    gap="16px", width="100%",
                ),
                rx.box(rx.text("No files yet. Upload files inside a project.",
                               color="var(--gray-9)"),
                       padding="40px", border="1px dashed var(--gray-6)",
                       border_radius="12px", text_align="center"),
            ),
            flex="1", padding="32px 40px", height="100vh",
            overflow_y="auto", background=CARD_BG,
        ),
        spacing="0", width="100%", align="start",
    )


# --------------------------------------------------------------------------- #
#  Cowork  (/cowork) — General (non-project) chat space
# --------------------------------------------------------------------------- #
def cowork_page() -> rx.Component:
    return rx.hstack(
        sidebar(),
        rx.box(
            rx.heading("General", size="7", weight="bold", margin_bottom="2px"),
            rx.text("Chats not tied to a project.", size="2",
                    color="var(--gray-9)", margin_bottom="20px"),
            workspace_composer(),
            rx.text("Recent", size="2", weight="medium", color="var(--gray-10)",
                    margin_top="22px"),
            recent_tasks(),
            flex="1", padding="32px 40px", height="100vh",
            overflow_y="auto", background=CARD_BG, max_width="920px",
        ),
        spacing="0", width="100%", align="start",
    )


# --------------------------------------------------------------------------- #
#  Connectors  (/connectors) — real connection management
# --------------------------------------------------------------------------- #
def add_connector_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Add REST connector"),
            rx.dialog.description("Expose a REST API to the agent as a tool. When "
                                 "enabled, the agent can GET paths under the base URL.",
                                 size="2", color="var(--gray-10)"),
            rx.vstack(
                rx.input(placeholder="Name (e.g. Exchange Rates)",
                         value=AppState.conn_name, on_change=AppState.set_conn_name,
                         width="100%"),
                rx.input(placeholder="Base URL (e.g. https://api.example.com)",
                         value=AppState.conn_url, on_change=AppState.set_conn_url,
                         width="100%"),
                rx.input(placeholder="Auth header name (optional, e.g. Authorization)",
                         value=AppState.conn_hkey, on_change=AppState.set_conn_hkey,
                         width="100%"),
                rx.input(placeholder="Auth header value (optional)",
                         value=AppState.conn_hval, on_change=AppState.set_conn_hval,
                         width="100%"),
                spacing="3", margin_y="14px", width="100%",
            ),
            rx.hstack(
                rx.dialog.close(
                    rx.button("Cancel", variant="soft", color_scheme="gray",
                              type="button",
                              on_click=lambda: AppState.set_conn_add_open(False))),
                rx.button("Add connector", type="button",
                          on_click=AppState.save_connector),
                spacing="3", justify="end",
            ),
            max_width="480px",
        ),
        open=AppState.conn_add_open, on_open_change=AppState.set_conn_add_open,
    )


def connector_row(c: rx.Var) -> rx.Component:
    return rx.hstack(
        rx.icon("circle", size=10,
                color=rx.cond(c["status"] == "error", "var(--red-9)", "var(--green-9)")),
        rx.vstack(
            rx.hstack(
                rx.text(c["name"], size="3", weight="medium", color="var(--gray-12)"),
                rx.badge(c["type"], size="1", variant="soft", color_scheme="gray"),
                rx.badge(c["status"], size="1", variant="soft",
                         color_scheme=rx.cond(c["status"] == "error", "red", "green")),
                spacing="2", align="center",
            ),
            rx.text(c["detail"], size="1", color="var(--gray-9)", no_of_lines=1),
            spacing="1", align="start", flex="1", min_width="0",
        ),
        rx.spacer(),
        rx.cond(
            c["type"] == "rest",
            rx.hstack(
                rx.button(
                    rx.cond(AppState.enabled_connectors.contains(c["id"]),
                            "Enabled", "Enable"),
                    size="1", color_scheme="gray",
                    variant=rx.cond(AppState.enabled_connectors.contains(c["id"]),
                                    "solid", "soft"),
                    on_click=AppState.toggle_connector(c["id"])),
                rx.button("Test", size="1", variant="soft", color_scheme="gray",
                          on_click=AppState.test_user_connector(c["id"])),
                rx.button(rx.icon("trash-2", size=13), size="1", variant="soft",
                          color_scheme="red",
                          on_click=AppState.remove_user_connector(c["id"])),
                spacing="2",
            ),
            rx.fragment(),
        ),
        width="100%", align="center", spacing="3", padding="14px 6px",
        border_bottom=BORDER,
    )


def connectors_page() -> rx.Component:
    return rx.hstack(
        sidebar(),
        rx.box(
            rx.hstack(
                rx.heading("Connectors", size="7", weight="bold"),
                rx.spacer(),
                rx.button(rx.icon("plus", size=16), "Add connector",
                          on_click=AppState.open_add_connector),
                width="100%", align="center", margin_bottom="6px",
            ),
            rx.text("Built-in sources show live status. Add REST connectors and enable "
                    "them to give the agent new tools.", size="2",
                    color="var(--gray-9)", margin_bottom="18px"),
            rx.cond(
                AppState.conn_test != "",
                rx.box(rx.text(AppState.conn_test, size="1", color="var(--gray-11)"),
                       padding="8px 12px", background="var(--gray-2)",
                       border_radius="8px", margin_bottom="14px"),
            ),
            rx.vstack(rx.foreach(AppState.connectors, connector_row),
                      spacing="0", width="100%"),
            add_connector_dialog(),
            flex="1", padding="32px 40px", height="100vh",
            overflow_y="auto", background=CARD_BG,
        ),
        spacing="0", width="100%", align="start",
    )


# --------------------------------------------------------------------------- #
#  Workspace
# --------------------------------------------------------------------------- #
def panel_header(title: str, *controls) -> rx.Component:
    return rx.hstack(
        rx.text(title, size="3", weight="medium", color="var(--gray-12)"),
        rx.spacer(),
        *controls,
        width="100%", align="center", margin_bottom="8px",
    )


def memory_panel() -> rx.Component:
    return rx.box(
        panel_header(
            "Memory",
            rx.badge(rx.icon("lock", size=11), "Only you", variant="soft",
                     color_scheme="gray", size="1"),
        ),
        rx.text(AppState.memory_display, size="2", color="var(--gray-11)",
                line_height="1.5"),
        rx.cond(
            AppState.memory_updated != "",
            rx.text("Last updated ", AppState.memory_updated, size="1",
                    color="var(--gray-9)", margin_top="8px"),
        ),
        padding="16px", border_bottom=BORDER,
    )


def instructions_panel() -> rx.Component:
    return rx.box(
        panel_header(
            "Instructions",
            rx.cond(
                AppState.editing_instructions,
                rx.fragment(),
                rx.icon("pencil", size=15, color="var(--gray-9)",
                        cursor="pointer", on_click=AppState.start_edit_instructions),
            ),
        ),
        rx.cond(
            AppState.editing_instructions,
            rx.vstack(
                rx.text_area(value=AppState.instructions_draft,
                             on_change=AppState.set_instructions_draft,
                             width="100%", rows="6"),
                rx.hstack(
                    rx.button("Save", size="1", on_click=AppState.save_instructions),
                    rx.button("Cancel", size="1", variant="soft", color_scheme="gray",
                              on_click=AppState.cancel_edit_instructions),
                    spacing="2", justify="end", width="100%",
                ),
                spacing="2", width="100%",
            ),
            rx.text(AppState.instructions_display, size="2", color="var(--gray-11)",
                    line_height="1.5", white_space="pre-wrap"),
        ),
        padding="16px", border_bottom=BORDER,
    )


def file_row(f: rx.Var) -> rx.Component:
    return rx.hstack(
        rx.icon("file-text", size=15, color="var(--gray-9)"),
        rx.text(f["name"], size="1", no_of_lines=1, flex="1"),
        rx.text(f["meta"], size="1", color="var(--gray-9)"),
        rx.badge(f["badge"], size="1", variant="soft", color_scheme="gray"),
        spacing="2", align="center", width="100%",
        padding="6px 8px", border_radius="6px", background="var(--gray-2)",
    )


def files_panel() -> rx.Component:
    return rx.box(
        panel_header(
            "Files",
            rx.upload(
                rx.icon("plus", size=15, color="var(--gray-9)", cursor="pointer"),
                id="kb_upload",
                on_drop=AppState.handle_upload(rx.upload_files(upload_id="kb_upload")),
                border="none", padding="0",
            ),
        ),
        rx.hstack(
            rx.text(AppState.cap_pct, "% of project capacity used",
                    size="1", color="var(--gray-9)"),
            rx.spacer(),
            rx.text(AppState.cap_used, " MB / ", AppState.cap_max, " MB",
                    size="1", color="var(--gray-9)"),
            width="100%", margin_bottom="6px",
        ),
        rx.progress(value=AppState.cap_pct, max=100, height="6px",
                    margin_bottom="12px"),
        rx.cond(
            AppState.has_files,
            rx.vstack(rx.foreach(AppState.files, file_row), spacing="2",
                      width="100%"),
            rx.text("No files yet. Use the + to upload into this project's KB.",
                    size="1", color="var(--gray-9)"),
        ),
        rx.cond(AppState.uploading,
                rx.text("Uploading…", size="1", color="var(--accent-9)",
                        margin_top="8px")),
        padding="16px",
    )


def _user_bubble(m: rx.Var) -> rx.Component:
    return rx.box(
        rx.text(m["content"], size="2", color="var(--accent-contrast)",
                white_space="pre-wrap"),
        background="var(--coral-strong)", padding="8px 12px", border_radius="12px",
        max_width="80%", margin_left="auto",
    )


def _final_bubble(m: rx.Var) -> rx.Component:
    return rx.box(
        rx.markdown(m["content"]),
        background="var(--gray-2)", padding="4px 14px", border_radius="12px",
        max_width="92%",
    )


def _tool_card(m: rx.Var, idx: rx.Var) -> rx.Component:
    """Claude-style tool card: tool icon + gerund label (running→done tense flip) +
    status glyph (spinner→check→alert), with a collapsible body holding the input and
    the result summary. Collapsed when done, auto-expanded on error."""
    running = m["status"] == "running"
    error = m["status"] == "error"
    show = rx.cond(error, True, AppState.expanded_tools.contains(idx))
    has_body = (m["input"] != "") | (m["summary"] != "") | (m["error"] != "")
    return rx.box(
        rx.hstack(
            rx.icon(m["icon"], size=14, color="var(--gray-9)"),
            rx.text(rx.cond(running, m["label_running"], m["label_done"]),
                    size="1", weight="medium", color="var(--gray-11)"),
            rx.cond(
                running, rx.spinner(size="1"),
                rx.cond(error,
                        rx.icon("circle-alert", size=13, color="var(--red-9)"),
                        rx.icon("check", size=13, color="var(--gray-9)"))),
            rx.spacer(),
            rx.cond(has_body,
                    rx.cond(show,
                            rx.icon("chevron-down", size=14, color="var(--gray-9)"),
                            rx.icon("chevron-right", size=14, color="var(--gray-9)")),
                    rx.fragment()),
            spacing="2", align="center", width="100%", cursor="pointer",
            on_click=AppState.toggle_tool(idx),
        ),
        rx.cond(
            show,
            rx.vstack(
                rx.cond(
                    m["input"] != "",
                    rx.box(rx.text(m["input"], size="1", white_space="pre-wrap",
                                   font_family="var(--code-font-family)",
                                   color="var(--gray-10)"),
                           background="var(--gray-2)", padding="6px 10px",
                           border_radius="8px", width="100%", overflow_x="auto"),
                    rx.fragment()),
                rx.cond(
                    m["error"] != "",
                    rx.text(m["error"], size="1", color="var(--red-11)",
                            white_space="pre-wrap"),
                    rx.cond(m["summary"] != "",
                            rx.text(m["summary"], size="1", color="var(--gray-9)",
                                    no_of_lines=4),
                            rx.fragment())),
                spacing="2", align="start", width="100%", margin_top="6px",
            ),
            rx.fragment(),
        ),
        border=rx.cond(error, "1px solid var(--red-6)", BORDER),
        border_radius="12px", padding="8px 12px", background="var(--gray-1)",
        width="100%", max_width="92%",
    )


def _table_block(m: rx.Var) -> rx.Component:
    return rx.box(
        rx.markdown(m["content"]),
        border=BORDER, border_radius="10px", padding="6px 14px",
        background=CARD_BG, max_width="100%", overflow_x="auto",
    )


def _error_bubble(m: rx.Var) -> rx.Component:
    return rx.box(
        rx.text(m["content"], size="2", color="var(--red-11)", white_space="pre-wrap"),
        background="var(--red-2)", padding="8px 12px", border_radius="12px",
        max_width="92%",
    )


def _thinking_block(m: rx.Var, idx: rx.Var) -> rx.Component:
    """Claude-style collapsible reasoning block: muted header ('Thinking…' while
    streaming → 'Thought for Ns' when done) + chevron, with a left-railed body that
    is open while streaming and auto-collapses when done (click to re-expand)."""
    done = m["done"] == "1"
    expanded = rx.cond(done, AppState.expanded_thoughts.contains(idx), True)
    return rx.vstack(
        rx.hstack(
            rx.cond(expanded,
                    rx.icon("chevron-down", size=14, color="var(--gray-9)"),
                    rx.icon("chevron-right", size=14, color="var(--gray-9)")),
            rx.cond(
                done,
                rx.text(m["label"], size="1", weight="medium", color="var(--gray-11)"),
                rx.hstack(
                    rx.spinner(size="1"),
                    rx.text("Thinking…", size="1", weight="medium",
                            color="var(--gray-11)"),
                    spacing="2", align="center"),
            ),
            spacing="1", align="center", cursor="pointer",
            on_click=AppState.toggle_thought(idx),
            _hover={"opacity": 0.75},
        ),
        rx.cond(
            expanded,
            rx.box(
                rx.markdown(m["content"]),
                border_left="1.5px solid var(--gray-5)",
                padding_left="14px", margin_left="6px", margin_top="2px",
                font_size="0.9em", opacity="0.8",
            ),
            rx.fragment(),
        ),
        spacing="1", align="start", width="100%", padding_y="2px",
    )


def _source_row(s: rx.Var) -> rx.Component:
    return rx.link(
        rx.hstack(
            rx.cond(
                s["favicon"] != "",
                rx.image(src=s["favicon"], width="16px", height="16px",
                         border_radius="3px", flex_shrink="0"),
                rx.icon("globe", size=16, color="var(--gray-9)"),
            ),
            rx.vstack(
                rx.text(s["title"], size="2", weight="medium", no_of_lines=1,
                        color="var(--gray-12)"),
                rx.text(s["domain"], size="1", color="var(--gray-9)", no_of_lines=1),
                rx.cond(
                    s["snippet"] != "",
                    rx.text(s["snippet"], size="1", color="var(--gray-10)",
                            no_of_lines=2),
                    rx.fragment(),
                ),
                spacing="0", align="start", width="100%",
            ),
            spacing="2", align="start", width="100%",
        ),
        href=s["url"], is_external=True, width="100%", text_decoration="none",
        padding="6px 8px", border_radius="8px",
        _hover={"background": "var(--gray-3)"},
    )


def _sources_block(m: rx.Var, idx: rx.Var) -> rx.Component:
    items = m["items"].to(list[dict[str, str]])
    expanded = AppState.expanded_sources.contains(idx)
    return rx.box(
        rx.hstack(
            rx.icon("book-open", size=14, color="var(--gray-9)"),
            rx.text("Sources", size="1", weight="medium", color="var(--gray-11)"),
            rx.badge(items.length(), color_scheme="gray", size="1", variant="soft"),
            rx.cond(expanded,
                    rx.icon("chevron-down", size=14, color="var(--gray-9)"),
                    rx.icon("chevron-right", size=14, color="var(--gray-9)")),
            spacing="2", align="center", cursor="pointer",
            on_click=AppState.toggle_sources(idx), _hover={"opacity": 0.75},
        ),
        rx.cond(
            expanded,
            rx.vstack(rx.foreach(items, _source_row), spacing="1", width="100%",
                      margin_top="6px"),
            rx.fragment(),
        ),
        border_top="1px solid var(--gray-4)", margin_top="8px", padding_top="8px",
        width="100%", max_width="92%",
    )


def render_message(m: rx.Var, idx: rx.Var) -> rx.Component:
    return rx.match(
        m["kind"],
        ("user", _user_bubble(m)),
        ("final", _final_bubble(m)),
        ("table", _table_block(m)),
        ("tool", _tool_card(m, idx)),
        ("thinking", _thinking_block(m, idx)),
        ("thought", _thinking_block(m, idx)),   # legacy single-line thoughts
        ("sources", _sources_block(m, idx)),
        ("error", _error_bubble(m)),
        _final_bubble(m),
    )


def thinking_indicator() -> rx.Component:
    return rx.hstack(
        rx.spinner(size="2"),
        rx.text("Thinking", size="2", color="var(--gray-10)"),
        spacing="2", align="center", padding_y="6px",
    )


# --------------------------------------------------------------------------- #
#  Composer — identical to Claude's input bar (+ menu, model pill, send)
# --------------------------------------------------------------------------- #
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


def conversation_row(c: rx.Var) -> rx.Component:
    return rx.link(
        rx.vstack(
            rx.text(c["title"], size="2", weight="medium", color="var(--gray-12)",
                    no_of_lines=1),
            rx.text("Last message ", c["updated_rel"], size="1", color="var(--gray-9)"),
            spacing="1", align="start", width="100%",
        ),
        href=c["href"], width="100%", padding="14px 6px", border_top=BORDER,
        _hover={"background": "var(--gray-2)"},
    )


def recent_tasks() -> rx.Component:
    return rx.cond(
        AppState.conversations,
        rx.vstack(rx.foreach(AppState.conversations, conversation_row),
                  spacing="0", width="100%"),
        rx.text("No conversations yet. Ask something above to start one.",
                size="1", color="var(--gray-9)", padding_y="18px"),
    )


def workspace() -> rx.Component:
    return rx.hstack(
        sidebar(),
        rx.box(
            rx.link(
                rx.hstack(rx.icon("arrow-left", size=14), rx.text("All projects"),
                          spacing="1", align="center"),
                href="/", color="var(--gray-9)", size="2", margin_bottom="16px",
            ),
            rx.hstack(
                rx.heading(AppState.current_name, size="7", weight="bold"),
                rx.spacer(),
                rx.icon("ellipsis-vertical", size=18, color="var(--gray-9)"),
                rx.icon("pin", size=18, color="var(--gray-9)"),
                rx.icon("trash-2", size=18, color="var(--red-9)", cursor="pointer",
                        on_click=AppState.delete_current_project),
                width="100%", align="center", margin_bottom="20px", spacing="3",
            ),
            rx.hstack(
                # Left column — composer + recent conversations (Claude-style)
                rx.vstack(
                    workspace_composer(),
                    rx.text("Recent", size="2", weight="medium",
                            color="var(--gray-10)", margin_top="22px"),
                    recent_tasks(),
                    spacing="2", align="stretch", flex="1.6", min_width="0",
                ),
                # Right column — Memory / Instructions / Files
                rx.box(
                    memory_panel(),
                    instructions_panel(),
                    files_panel(),
                    flex="1", min_width="0", border=BORDER, border_radius="14px",
                    overflow="hidden", background=CARD_BG,
                ),
                spacing="6", width="100%", align="start",
            ),
            flex="1", padding="32px 40px", height="100vh",
            overflow_y="auto", background=CARD_BG,
        ),
        spacing="0", width="100%", align="start",
    )


# --------------------------------------------------------------------------- #
#  Conversation page  (/project/[pid]/c/[cid]) — the "typical" chat view
# --------------------------------------------------------------------------- #
def rename_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Rename conversation"),
            rx.input(value=AppState.rename_draft, on_change=AppState.set_rename_draft,
                     width="100%", margin_y="12px"),
            rx.hstack(
                rx.dialog.close(
                    rx.button("Cancel", variant="soft", color_scheme="gray",
                              on_click=lambda: AppState.set_rename_open(False))),
                rx.button("Save", on_click=AppState.save_rename),
                spacing="3", justify="end",
            ),
            max_width="420px",
        ),
        open=AppState.rename_open, on_open_change=AppState.set_rename_open,
    )


def move_target_row(t: rx.Var) -> rx.Component:
    return rx.button(
        rx.icon("folder", size=14), t["name"],
        on_click=AppState.move_to_project(t["id"]),
        variant="soft", color_scheme="gray", width="100%", justify="start",
    )


def change_project_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Change project"),
            rx.dialog.description("Move this conversation to another space.",
                                  size="2", color="var(--gray-10)"),
            rx.vstack(
                rx.foreach(AppState.move_targets, move_target_row),
                spacing="2", width="100%", margin_y="12px",
                max_height="320px", overflow_y="auto",
            ),
            rx.hstack(
                rx.dialog.close(
                    rx.button("Cancel", variant="soft", color_scheme="gray",
                              on_click=lambda: AppState.set_change_open(False))),
                justify="end", width="100%",
            ),
            max_width="420px",
        ),
        open=AppState.change_open, on_open_change=AppState.set_change_open,
    )


def conversation_menu() -> rx.Component:
    return rx.menu.root(
        rx.menu.trigger(
            rx.hstack(
                rx.text(AppState.conv_title, size="2", color="var(--gray-12)",
                        no_of_lines=1),
                rx.icon("chevron-down", size=14, color="var(--gray-9)"),
                spacing="1", align="center", cursor="pointer",
            ),
        ),
        rx.menu.content(
            rx.menu.item(rx.icon("pin", size=14),
                         rx.cond(AppState.conv_pinned, "Unpin", "Pin"),
                         on_click=AppState.toggle_pin),
            rx.menu.item(rx.icon("pencil", size=14), "Rename",
                         on_click=AppState.open_rename),
            rx.menu.item(rx.icon("folder-input", size=14), "Change project",
                         on_click=AppState.open_change_project),
            rx.menu.item(rx.icon("folder-minus", size=14), "Remove from project",
                         on_click=AppState.remove_from_project,
                         disabled=AppState.is_general),
            rx.menu.separator(),
            rx.menu.item(rx.icon("trash-2", size=14), "Delete",
                         color="var(--red-11)",
                         on_click=AppState.delete_current_conversation),
        ),
    )


def conversation_page() -> rx.Component:
    return rx.hstack(
        sidebar(),
        rx.vstack(
            # Breadcrumb header with the conversation menu (▾)
            rx.hstack(
                rx.link(rx.text(AppState.current_name, size="2", weight="medium",
                                color="var(--gray-11)"),
                        href=AppState.workspace_href, underline="none"),
                rx.text("/", size="2", color="var(--gray-8)"),
                conversation_menu(),
                rx.spacer(),
                rename_dialog(),
                change_project_dialog(),
                width="100%", align="center", padding="14px 24px",
                border_bottom=BORDER,
            ),
            # Message stream
            rx.box(
                rx.vstack(
                    rx.foreach(AppState.messages,
                               lambda m, i: render_message(m, i)),
                    rx.cond(AppState.is_running, thinking_indicator()),
                    spacing="4", width="100%", max_width="780px",
                    margin="0 auto", padding_bottom="20px",
                ),
                flex="1", width="100%", overflow_y="auto", padding="24px 16px",
            ),
            # Composer
            rx.box(
                rx.box(
                    composer(AppState.send_message, "Write a message…"),
                    max_width="820px", margin="0 auto", width="100%",
                ),
                padding="14px 16px", border_top=BORDER, width="100%",
                background=CARD_BG,
            ),
            height="100vh", width="100%", spacing="0", background=CARD_BG,
        ),
        spacing="0", width="100%", align="start",
    )


# --------------------------------------------------------------------------- #
#  App
# --------------------------------------------------------------------------- #
app = rx.App(
    stylesheets=["/theme.css"],
    style={"fontFamily": "var(--default-font-family)"},
)
app.add_page(dashboard, route="/", on_load=AppState.load_dashboard,
             title="AJ360 · Projects")
app.add_page(workspace, route="/project/[pid]", on_load=AppState.load_workspace,
             title="AJ360 · Project")
app.add_page(conversation_page, route="/project/[pid]/c/[cid]",
             on_load=AppState.load_conversation, title="AJ360 · Chat")
app.add_page(chats_dashboard, route="/chats", on_load=AppState.load_chats,
             title="AJ360 · Chats")
app.add_page(customize_page, route="/customize", on_load=AppState.load_customize,
             title="AJ360 · Customize")
app.add_page(code_page, route="/code", on_load=AppState.load_code,
             title="AJ360 · Code")
app.add_page(artifacts_page, route="/artifacts", on_load=AppState.load_artifacts,
             title="AJ360 · Artifacts")
app.add_page(cowork_page, route="/cowork", on_load=AppState.load_cowork,
             title="AJ360 · General")
app.add_page(connectors_page, route="/connectors",
             on_load=AppState.load_connectors_page, title="AJ360 · Connectors")
