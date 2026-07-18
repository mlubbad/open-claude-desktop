"""The agent must know the current date & time on every turn.

Root cause covered here: the system prompt used to be fully static, so the model
had no "now" anchor — it guessed dates from tool-result data or burned a docker
code-execution call just to learn the time. `util.temporal_context()` is the
single shared clock line; `_system_prompt` appends it (last, so the static
prefix stays cache-stable) and `run_turn` rebuilds it fresh each turn.
"""
from __future__ import annotations

import asyncio
import pathlib
import re
from datetime import datetime, timedelta, timezone

from ocd_core import agent, util

FIXED = datetime(2026, 7, 18, 14, 32, tzinfo=timezone.utc)   # a Saturday
LATER = datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)


def test_temporal_context_renders_fixed_instant():
    block = util.temporal_context(FIXED)
    assert "# TEMPORAL CONTEXT" in block
    assert "Saturday 2026-07-18 14:32 UTC" in block           # weekday + date + minute
    assert re.search(r"local \d{2}:\d{2} UTC[+-]\d{2}:\d{2}", block)


def test_temporal_context_defaults_to_real_now():
    block = util.temporal_context()
    m = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) UTC", block)
    assert m, block
    stamped = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M").replace(
        tzinfo=timezone.utc)
    assert abs(datetime.now(timezone.utc) - stamped) < timedelta(minutes=5)


def test_system_prompt_contains_temporal_context_in_all_variants():
    for kw in ({}, {"bigquery": True}, {"memory": True},
               {"project_instructions": "be nice"}):
        sp = agent._system_prompt(**kw)
        assert "# TEMPORAL CONTEXT" in sp, kw


def test_temporal_context_is_last_block_for_cache_stable_prefix():
    sp = agent._system_prompt(project_instructions="x", skill_instructions="y",
                              research=True, memory=True, bigquery=True)
    idx = sp.index("# TEMPORAL CONTEXT")
    for marker in ("# BIGQUERY", "# MEMORY PROTOCOL", "# PROJECT-SPECIFIC",
                   "# ACTIVE SKILL", "# RESEARCH MODE"):
        assert sp.index(marker) < idx, marker


def test_system_prompt_stamp_refreshes_per_call():
    a = agent._system_prompt(now=FIXED)
    b = agent._system_prompt(now=LATER)
    assert "2026-07-18" in a and "2026-12-31" in b
    assert a != b


def test_run_turn_sends_time_aware_system_prompt(monkeypatch):
    captured = {}

    async def fake_stream_llm(llm, model, messages, tools=None, *args, **kw):
        captured["system"] = messages[0]["content"]
        yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", fake_stream_llm)
    monkeypatch.setattr(agent, "get_llm_client", lambda: object())
    monkeypatch.setattr(agent.schema_catalog, "ensure_catalog", lambda: None)

    async def run():
        async for _ in agent.run_turn("hi", [], None, "glm-4-flash",
                                      effort="Low"):
            pass

    asyncio.run(run())
    assert "# TEMPORAL CONTEXT" in captured["system"]
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC", captured["system"])


def test_chainlit_surface_also_injects_temporal_context():
    # The legacy Chainlit monolith (root app.py) must stamp its system prompt
    # too — via the same shared ocd_core.util helper, not a private copy.
    src = pathlib.Path(__file__).resolve().parents[2].joinpath(
        "app.py").read_text(encoding="utf-8")
    assert "temporal_context" in src
