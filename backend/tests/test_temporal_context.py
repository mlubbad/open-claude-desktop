"""Per-turn time awareness (port of the dev-main fix, cache-safe for this line).

The agent previously knew only a bare "Today's date is X" (server-local, no clock,
no timezone, no weekday), so it could not judge "has the 09:30 UTC job fired?" or
interpret data timestamps against "now".

The full stamp rides on the NEWEST user message, NOT the system prompt:
anthropic_native puts a cache_control breakpoint on the system blocks, and
Anthropic prompt caching is prefix-hierarchical — a minute-granular stamp in the
system prompt would invalidate the whole conversation cache every turn. The
newest user message is never part of the cached prefix, so stamping it is free;
prior history stays byte-identical.
"""
import asyncio
import re
from datetime import datetime, timedelta, timezone

from ocd_core import agent, prompts

FIXED = datetime(2026, 7, 18, 14, 32, tzinfo=timezone.utc)   # a Saturday
LATER = datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)


def test_temporal_context_renders_fixed_instant():
    block = prompts.temporal_context(FIXED)
    assert block.startswith("<temporal_context>")
    assert block.rstrip().endswith("</temporal_context>")
    assert "Saturday 2026-07-18 14:32 UTC" in block   # weekday + date + minute
    assert re.search(r"local \d{2}:\d{2} UTC[+-]\d{2}:\d{2}", block)


def test_temporal_context_defaults_to_real_now():
    block = prompts.temporal_context()
    m = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) UTC", block)
    assert m, block
    stamped = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M").replace(
        tzinfo=timezone.utc)
    assert abs(datetime.now(timezone.utc) - stamped) < timedelta(minutes=5)


def test_temporal_context_refreshes_per_call():
    a = prompts.temporal_context(FIXED)
    b = prompts.temporal_context(LATER)
    assert "2026-07-18" in a and "2026-12-31" in b
    assert a != b


def _drive(gen):
    async def _collect():
        return [ev async for ev in gen]
    return asyncio.run(_collect())


def _patch_client(monkeypatch):
    monkeypatch.setattr(agent, "resolve_turn_client",
                        lambda model, provider=None: (object(), model, None))
    monkeypatch.setattr(agent.schema_catalog, "ensure_catalog", lambda: None)


def test_run_turn_stamps_newest_user_message_only(monkeypatch):
    """The stamp is on the new user message (once), history is untouched, and the
    system prompt keeps only the static daily date line — the cached prefix
    (system + prior history) stays byte-identical across turns."""
    _patch_client(monkeypatch)
    captured = {}

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        captured["messages"] = [dict(m) for m in messages]
        yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    history = [{"role": "user", "content": "earlier question"},
               {"role": "assistant", "content": "earlier answer"}]
    _drive(agent.run_turn("what time is it?", list(history), None, "m",
                          effort="Low"))

    msgs = captured["messages"]
    last = msgs[-1]
    assert last["role"] == "user"
    assert "<temporal_context>" in last["content"]
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC", last["content"])
    assert last["content"].rstrip().endswith("what time is it?")

    # Cache safety: exactly ONE stamp in the whole request...
    stamped = [m for m in msgs
               if "<temporal_context>" in str(m.get("content", ""))]
    assert stamped == [last]
    # ...prior history is byte-identical...
    assert msgs[1]["content"] == "earlier question"
    assert msgs[2]["content"] == "earlier answer"
    # ...and the system prompt carries no per-minute stamp, just the date line.
    assert "<temporal_context>" not in msgs[0]["content"]
    assert "Today's date is" in msgs[0]["content"]
