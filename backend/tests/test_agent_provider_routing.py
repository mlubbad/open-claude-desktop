"""Phase 1b: run_turn resolves the per-turn provider/model and fails cleanly on BYOK."""
import asyncio

import pytest
from ocd_core import agent, secrets
from ocd_core.llm import client as llm_client


@pytest.fixture(autouse=True)
def _mem(monkeypatch):
    monkeypatch.setenv("OCD_SECRET_BACKEND", "memory")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    secrets.reset_store()
    llm_client.reset_clients()
    # Keep the turn hermetic: no BigQuery catalog build.
    monkeypatch.setattr(agent.schema_catalog, "ensure_catalog", lambda: None)
    yield
    secrets.reset_store()
    llm_client.reset_clients()


def _drive(agen):
    async def run():
        return [ev async for ev in agen]
    return asyncio.run(run())


def test_missing_key_yields_clean_error_no_crash():
    evs = _drive(agent.run_turn("hi", [], None, "gpt-4o", provider="openai", effort="Low"))
    assert len(evs) == 1
    assert evs[0]["type"] == "error"
    assert "OpenAI" in evs[0]["text"] or "key" in evs[0]["text"].lower()


def test_routes_to_selected_provider_and_fallback(monkeypatch):
    captured = {}

    async def fake_stream(llm, model, messages, tools=None, temperature=0.1,
                          max_tokens=4096, content_scope="answer", fallback_model=None, **_kw):
        captured["base_url"] = str(llm.base_url)
        captured["model"] = model
        captured["fallback"] = fallback_model
        yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", fake_stream)
    # ollama needs no key; the 'provider/model' prefix selects it.
    _drive(agent.run_turn("hi", [], None, "ollama/fast-mistral", effort="Low"))
    assert "localhost:11434" in captured["base_url"]
    assert captured["model"] == "fast-mistral"
    assert captured["fallback"] is None  # ollama default == requested model
