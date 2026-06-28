"""Conversation page (/project/[pid]/c/[cid]) — the "typical" chat view."""
import reflex as rx

from ..state import AppState
from .theme import BORDER, CARD_BG
from .sidebar import sidebar
from .composer import composer
from .chat_panel import render_message, thinking_indicator


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
