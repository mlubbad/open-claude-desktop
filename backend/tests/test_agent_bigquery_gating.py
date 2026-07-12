"""Phase 2: BigQuery tools + prompt appear ONLY when the connector is enabled."""
import asyncio

import pytest
from ocd_core import agent, config, secrets
from ocd_core.llm import client as llm_client


@pytest.fixture(autouse=True)
def _mem(monkeypatch):
    monkeypatch.setenv("OCD_SECRET_BACKEND", "memory")
    secrets.reset_store()
    llm_client.reset_clients()
    monkeypatch.setattr(agent.schema_catalog, "ensure_catalog", lambda: None)
    yield
    secrets.reset_store()
    llm_client.reset_clients()


def _capture_turn(monkeypatch):
    seen = {}

    async def fake_stream(llm, model, messages, tools, temperature, max_tokens,
                          content_scope="answer", fallback_model=None, **_kw):
        seen["tools"] = [t["function"]["name"] for t in (tools or [])]
        seen["system"] = messages[0]["content"]
        yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", fake_stream)

    async def run():
        async for _ in agent.run_turn("hi", [], None, "ollama/llama3.1", effort="Low"):
            pass
    asyncio.run(run())
    return seen


def test_bigquery_off_is_pure_assistant(monkeypatch):
    monkeypatch.setattr(config, "BIGQUERY_ENABLED", False)
    seen = _capture_turn(monkeypatch)
    assert "search_schema" not in seen["tools"]
    assert "run_sql" not in seen["tools"]
    assert "bigquery" not in seen["system"].lower()
    assert "aj360" not in seen["system"].lower()


def test_bigquery_on_exposes_tools_and_prompt(monkeypatch):
    monkeypatch.setattr(config, "BIGQUERY_ENABLED", True)
    seen = _capture_turn(monkeypatch)
    assert "search_schema" in seen["tools"]
    assert "run_sql" in seen["tools"]
    assert "BIGQUERY" in seen["system"]
