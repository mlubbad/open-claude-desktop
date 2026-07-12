"""Usage/cost estimation + the `usage` event emitted at the end of a turn."""
import asyncio

import pytest
from ocd_core import agent, secrets, usage
from ocd_core.llm import client as llm_client


def test_estimate_text_and_messages():
    assert usage.estimate_text("") == 0
    assert usage.estimate_text("abcd") == 1  # ~4 chars/token
    msgs = [{"role": "user", "content": "hello there"},
            {"role": "assistant", "content": "hi", "tool_calls": [{"id": "x"}]}]
    assert usage.estimate_messages(msgs) > 0


def test_price_known_and_unknown():
    cost = usage.price_usd("gpt-4o", 1_000_000, 1_000_000)
    assert cost == pytest.approx(12.5)  # 2.5 in + 10 out
    assert usage.price_usd("some-unknown-model", 1000, 1000) is None
    # provider/model prefix is stripped
    assert usage.price_usd("openai/gpt-4o-mini", 1_000_000, 0) == pytest.approx(0.15)


def test_build_usage_shape():
    u = usage.build_usage("gpt-4o", [{"role": "user", "content": "hi"}], "an answer")
    assert u["type"] == "usage" and u["model"] == "gpt-4o"
    assert u["context_tokens"] > 0 and u["output_tokens"] > 0
    assert u["context_limit"] >= 128_000
    assert 0 <= u["context_pct"] <= 100
    assert u["cost_usd"] is not None


class _FakeToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = type("F", (), {"name": name, "arguments": arguments})()

    def model_dump(self):
        return {"id": self.id, "type": "function",
                "function": {"name": self.function.name, "arguments": self.function.arguments}}


@pytest.fixture
def _env(monkeypatch):
    monkeypatch.setenv("OCD_SECRET_BACKEND", "memory")
    secrets.reset_store()
    llm_client.reset_clients()
    monkeypatch.setattr(agent, "resolve_turn_client",
                        lambda model, provider=None: (object(), model, None))
    monkeypatch.setattr(agent.schema_catalog, "ensure_catalog", lambda: None)
    yield
    secrets.reset_store()
    llm_client.reset_clients()


def test_run_turn_emits_usage_event(monkeypatch, _env):
    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        yield {"type": "delta", "scope": "answer", "text": "the answer"}
        yield {"__done__": {"content": "the answer", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    async def scenario():
        return [ev async for ev in agent.run_turn("hi", [], None, "gpt-4o", effort="Low")]

    events = asyncio.run(scenario())
    usage_evs = [e for e in events if e.get("type") == "usage"]
    assert len(usage_evs) == 1
    u = usage_evs[0]
    assert u["context_tokens"] > 0 and u["context_limit"] > 0 and u["output_tokens"] > 0
    assert events[-1]["type"] == "usage"  # last event of the turn
