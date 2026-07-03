"""HITL end-to-end through run_turn: a sensitive tool suspends for approval."""
import asyncio

import pytest
from ocd_core import agent, config, permissions, secrets
from ocd_core.llm import client as llm_client


class _FakeToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = type("F", (), {"name": name, "arguments": arguments})()

    def model_dump(self):
        return {"id": self.id, "type": "function",
                "function": {"name": self.function.name, "arguments": self.function.arguments}}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("OCD_SECRET_BACKEND", "memory")
    secrets.reset_store()
    llm_client.reset_clients()
    monkeypatch.setattr(agent, "resolve_turn_client",
                        lambda model, provider=None: (object(), model, None))
    monkeypatch.setattr(agent.schema_catalog, "ensure_catalog", lambda: None)
    monkeypatch.setattr(config, "PERMISSION_TIMEOUT_SEC", 2)
    yield
    secrets.reset_store()
    llm_client.reset_clients()


def _run_turn_with_decision(monkeypatch, decision: bool, turn_id="t1"):
    """Drive a turn whose model calls `bash`, resolving the approval with `decision`."""
    executed = []

    async def _tool(name, args, tc_id, *a, **k):
        executed.append(name)
        return {"id": tc_id, "name": name, "ok": True, "result": "ran", "summary": ""}

    monkeypatch.setattr(agent, "_run_one_tool", _tool)

    state = {"n": 0}

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None):
        state["n"] += 1
        if state["n"] == 1:
            yield {"__done__": {"content": "", "note": None,
                                "tool_calls": [_FakeToolCall("c1", "bash", '{"command": "ls"}')]}}
        else:
            yield {"type": "delta", "scope": "answer", "text": "done"}
            yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    async def scenario():
        events = []

        async def resolver():
            for _ in range(400):
                if permissions.registry.pending(turn_id):
                    permissions.registry.resolve(turn_id, "c1", decision)
                    return
                await asyncio.sleep(0.005)

        task = asyncio.create_task(resolver())
        async for ev in agent.run_turn("hi", [], None, "m", effort="Low", bash=True,
                                       turn_id=turn_id, permission_mode="ask"):
            events.append(ev)
        await task
        return events, executed

    return asyncio.run(scenario())


def test_approval_required_then_approved_runs_tool(monkeypatch):
    events, executed = _run_turn_with_decision(monkeypatch, decision=True)
    types = [e["type"] for e in events]
    assert "approval_required" in types
    ar = next(e for e in events if e["type"] == "approval_required")
    assert ar["name"] == "bash" and ar["turn_id"] == "t1" and ar["id"] == "c1"
    assert "bash" in executed  # approved -> executed


def test_declined_does_not_run_tool(monkeypatch):
    events, executed = _run_turn_with_decision(monkeypatch, decision=False)
    types = [e["type"] for e in events]
    assert "approval_required" in types
    assert "bash" not in executed  # declined -> never executed
    err = next(e for e in events if e["type"] == "tool_error" and e["id"] == "c1")
    assert "Declined" in err["text"]


def test_auto_mode_never_prompts(monkeypatch):
    # Same setup but with the default gate off (no turn_id) -> runs immediately.
    executed = []

    async def _tool(name, args, tc_id, *a, **k):
        executed.append(name)
        return {"id": tc_id, "name": name, "ok": True, "result": "ran", "summary": ""}

    monkeypatch.setattr(agent, "_run_one_tool", _tool)
    state = {"n": 0}

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None):
        state["n"] += 1
        if state["n"] == 1:
            yield {"__done__": {"content": "", "note": None,
                                "tool_calls": [_FakeToolCall("c1", "bash", '{"command": "ls"}')]}}
        else:
            yield {"type": "delta", "scope": "answer", "text": "done"}
            yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    async def scenario():
        types = []
        async for ev in agent.run_turn("hi", [], None, "m", effort="Low", bash=True):
            types.append(ev["type"])
        return types

    types = asyncio.run(scenario())
    assert "approval_required" not in types
    assert "bash" in executed
