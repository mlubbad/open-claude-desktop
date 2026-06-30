"""Chat home (/) — Claude-Desktop-style: greeting + centered composer + chips."""
import reflex as rx

from ..state import AppState
from .composer import workspace_composer
from .sidebar import sidebar
from .theme import CARD_BG


def _chip(icon: str, label: str, **handler) -> rx.Component:
    return rx.button(
        rx.icon(icon, size=15), label,
        variant="soft", color_scheme="gray", size="2", radius="full",
        **handler,
    )


def home_hero() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.icon("sparkles", size=30, color="var(--accent-9)"),
            rx.heading(AppState.greeting + ", Mohammed", size="8", weight="medium",
                       color="var(--gray-12)"),
            spacing="3", align="center",
        ),
        rx.box(workspace_composer(), width="100%", margin_top="24px"),
        rx.hstack(
            _chip("database", "Query BigQuery", on_click=AppState.chip_query_bigquery),
            _chip("plus", "New project", on_click=rx.redirect("/projects")),
            _chip("messages-square", "Browse chats", on_click=rx.redirect("/chats")),
            _chip("sliders-horizontal", "Customize", on_click=rx.redirect("/customize")),
            spacing="2", margin_top="16px", wrap="wrap", justify="center",
        ),
        spacing="0", width="100%", max_width="720px", align="center",
    )


def home_page() -> rx.Component:
    return rx.hstack(
        sidebar(),
        rx.center(
            home_hero(),
            flex="1", height="100vh", padding="32px 40px",
            overflow_y="auto", background=CARD_BG,
        ),
        spacing="0", width="100%", align="start",
    )
