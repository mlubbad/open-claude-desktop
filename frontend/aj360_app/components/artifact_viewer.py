"""Code console, artifacts library, and connectors management pages."""
import reflex as rx

from ..state import AppState
from .sidebar import sidebar
from .theme import BORDER, CARD_BG


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
