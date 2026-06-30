"""Sidebar (shared shell) — Claude-style. Unimplemented items are disabled."""
import reflex as rx

from ..state import AppState
from .theme import BORDER, CARD_BG, PAGE_BG


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
        rx.cond(
            ~AppState.backend_ok,
            rx.box(
                rx.text(AppState.backend_error, size="1", color="white"),
                background="var(--red-9)", padding="6px 10px", width="100%",
            ),
        ),
        top_tabs(),
        rx.vstack(
            nav_item("plus", "New chat", href="/"),
            nav_item("folder", "Projects", href="/projects"),
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
