"""Chat transcript renderer — bubbles, tool cards, thinking blocks, sources."""
import reflex as rx

from ..state import AppState
from .theme import BORDER, CARD_BG


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
