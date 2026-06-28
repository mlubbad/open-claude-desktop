"""Dashboard + chats dashboard — project grid and cross-project conversation list."""
import reflex as rx

from ..state import AppState
from .theme import BORDER, CARD_BG
from .sidebar import sidebar


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
