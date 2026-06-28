"""Project workspace + cowork pages — memory/instructions/files panels and layout."""
import reflex as rx

from ..state import AppState
from .theme import BORDER, CARD_BG
from .sidebar import sidebar
from .composer import workspace_composer


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
