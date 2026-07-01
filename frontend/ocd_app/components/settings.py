"""Customize (/customize) — settings page."""
import reflex as rx

from ..state import AppState
from .theme import BORDER, CARD_BG
from .sidebar import sidebar


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
