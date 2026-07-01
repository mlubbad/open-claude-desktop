"""BigQuery is an optional capability, not the hard-wired identity."""
from __future__ import annotations

from ocd_core import agent


def test_base_prompt_is_generic_without_bigquery():
    sp = agent._system_prompt(bigquery=False)
    low = sp.lower()
    assert "open claude desktop" in low
    assert "search_schema" not in low            # BigQuery loop absent
    assert "banned aliases" not in low


def test_bigquery_prompt_present_when_enabled():
    sp = agent._system_prompt(bigquery=True)
    assert "search_schema" in sp
    assert "run_sql" in sp
    assert "AJ360" in sp


def test_bigquery_tools_gated(monkeypatch):
    captured = {}

    async def fake_stream_llm(llm, model, messages, tools=None, *args, **kw):
        captured["tools"] = tools
        captured["system"] = messages[0]["content"]
        yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", fake_stream_llm)
    monkeypatch.setattr(agent, "get_llm_client", lambda: object())
    monkeypatch.setattr(agent.schema_catalog, "ensure_catalog", lambda: None)

    import asyncio

    async def collect(bigquery):
        captured.clear()
        async for _ in agent.run_turn("hi", [], None, "glm-4-flash",
                                      effort="Low", bigquery=bigquery):
            pass
        names = {t["function"]["name"] for t in (captured["tools"] or [])}
        return names

    off = asyncio.run(collect(False))
    on = asyncio.run(collect(True))
    assert "search_schema" not in off and "run_sql" not in off
    assert "search_schema" in on and "run_sql" in on
