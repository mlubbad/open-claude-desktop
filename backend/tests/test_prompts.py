"""Phase 2: the system prompt is domain-agnostic and composed from opt-in sections."""
from datetime import date

from ocd_core import prompts


def test_base_prompt_has_no_bigquery_or_aj360():
    sp = prompts.build_system_prompt()
    low = sp.lower()
    assert "bigquery" not in low
    assert "aj360" not in low
    assert "sql" not in low
    # It IS a general assistant with tool-use + honesty guidance.
    assert "assistant" in low
    assert "honest" in low or "accurate" in low


def test_today_is_injected():
    sp = prompts.build_system_prompt(today=date(2026, 7, 3))
    assert "2026-07-03" in sp


def test_extra_section_is_appended():
    sp = prompts.build_system_prompt(extra_sections=["# CONNECTOR X\nDo the X thing."])
    assert "# CONNECTOR X" in sp
    assert "Do the X thing." in sp


def test_optional_sections_conditional():
    base = prompts.build_system_prompt()
    assert "MEMORY PROTOCOL" not in base
    assert "RESEARCH MODE" not in base
    assert "PROJECT-SPECIFIC" not in base

    full = prompts.build_system_prompt(
        memory=True, research=True, project_instructions="Only answer in French.",
        skill_instructions="Use the report skill.", user_profile="Call me Sam.")
    assert "MEMORY PROTOCOL" in full
    assert "RESEARCH MODE" in full
    assert "Only answer in French." in full
    assert "Use the report skill." in full
    assert "Call me Sam." in full


def test_empty_sections_are_skipped():
    sp = prompts.build_system_prompt(extra_sections=["", "   ", None])
    # Only the base remains; no stray blank sections.
    assert sp == prompts.build_system_prompt()
