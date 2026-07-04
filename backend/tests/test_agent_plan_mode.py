"""Plan mode (Phase 6).

`permission_mode="plan"` makes the agent research READ-ONLY, present a plan via the
`exit_plan_mode` tool, and only mutate after the user approves. Approving reuses the
existing HITL `approval_required` event + permission registry, and LEAVES plan mode so
the rest of the turn runs under the normal `ask` gate.

Driven against the real `run_turn` with a fake `_stream_llm`; `registry.wait` is
monkeypatched to stand in for the user's decision, so no live reply channel is needed.
"""
import asyncio

from ocd_core import agent


class _FakeToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = type("F", (), {"name": name, "arguments": arguments})()

    def model_dump(self):
        return {"id": self.id, "type": "function",
                "function": {"name": self.function.name,
                             "arguments": self.function.arguments}}


def _drive(gen):
    async def _collect():
        return [ev async for ev in gen]
    return asyncio.run(_collect())


def _patch_client(monkeypatch):
    monkeypatch.setattr(agent, "resolve_turn_client",
                        lambda model, provider=None: (object(), model, None))
    monkeypatch.setattr(agent.schema_catalog, "ensure_catalog", lambda: None)


def _spy_tools(monkeypatch, executed):
    async def _run(name, args, tc_id, *a, **k):
        executed.append(name)
        return {"id": tc_id, "name": name, "ok": True, "result": "ran", "summary": ""}
    monkeypatch.setattr(agent, "_run_one_tool", _run)


def test_plan_mode_blocks_sensitive_tool_and_offers_exit(monkeypatch):
    _patch_client(monkeypatch)
    executed, tool_sets, state = [], [], {"n": 0}
    _spy_tools(monkeypatch, executed)

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None):
        state["n"] += 1
        tool_sets.append([t["function"]["name"] for t in (tools or [])])
        if state["n"] == 1:
            yield {"__done__": {"content": "", "note": None, "tool_calls": [
                _FakeToolCall("c1", "bash", '{"command": "rm -rf /"}')]}}
        else:
            yield {"type": "delta", "scope": "answer", "text": "planning"}
            yield {"__done__": {"content": "planning", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    events = _drive(agent.run_turn("go", [], None, "m", effort="Low", bash=True,
                                   turn_id="t1", permission_mode="plan"))

    # bash never ran; it was blocked with a plan-mode tool_error.
    assert "bash" not in executed
    assert any(e.get("type") == "tool_error" and "plan mode" in e.get("text", "").lower()
               for e in events)
    # exit_plan_mode is offered to the model in plan mode.
    assert "exit_plan_mode" in tool_sets[0]


def test_exit_plan_mode_approval_leaves_plan_mode(monkeypatch):
    """Approving the plan unblocks mutation: the next tool runs (through the ask gate)."""
    _patch_client(monkeypatch)
    executed, state = [], {"n": 0}
    _spy_tools(monkeypatch, executed)

    async def _always_approve(turn_id, tc_id, timeout):
        return True
    monkeypatch.setattr(agent.permissions.registry, "wait", _always_approve)

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None):
        state["n"] += 1
        n = state["n"]
        if n == 1:
            yield {"__done__": {"content": "", "note": None, "tool_calls": [
                _FakeToolCall("c1", "exit_plan_mode", '{"plan": "1. edit x\\n2. test"}')]}}
        elif n == 2:  # plan approved -> now allowed to act
            yield {"__done__": {"content": "", "note": None, "tool_calls": [
                _FakeToolCall("c2", "bash", '{"command": "ls"}')]}}
        else:
            yield {"type": "delta", "scope": "answer", "text": "done"}
            yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    events = _drive(agent.run_turn("go", [], None, "m", effort="Low", bash=True,
                                   turn_id="t1", permission_mode="plan"))

    # The plan was presented for approval and marked approved.
    assert any(e.get("type") == "approval_required" and e["name"] == "exit_plan_mode"
               for e in events)
    assert any(e.get("type") == "tool_result" and "approved" in e.get("summary", "").lower()
               for e in events)
    # After approval, bash actually executed (proving plan mode was left).
    assert "bash" in executed


def test_exit_plan_mode_decline_keeps_blocking(monkeypatch):
    _patch_client(monkeypatch)
    executed, state = [], {"n": 0}
    _spy_tools(monkeypatch, executed)

    async def _always_decline(turn_id, tc_id, timeout):
        return False
    monkeypatch.setattr(agent.permissions.registry, "wait", _always_decline)

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None):
        state["n"] += 1
        n = state["n"]
        if n == 1:
            yield {"__done__": {"content": "", "note": None, "tool_calls": [
                _FakeToolCall("c1", "exit_plan_mode", '{"plan": "do it"}')]}}
        elif n == 2:  # still in plan mode -> this must be blocked
            yield {"__done__": {"content": "", "note": None, "tool_calls": [
                _FakeToolCall("c2", "bash", '{"command": "ls"}')]}}
        else:
            yield {"type": "delta", "scope": "answer", "text": "ok"}
            yield {"__done__": {"content": "ok", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    events = _drive(agent.run_turn("go", [], None, "m", effort="Low", bash=True,
                                   turn_id="t1", permission_mode="plan"))

    assert any(e.get("type") == "tool_result" and "planning" in e.get("summary", "").lower()
               for e in events)
    # Declining keeps plan mode on, so the later bash was blocked, not executed.
    assert "bash" not in executed
    assert any(e.get("type") == "tool_error" and "plan mode" in e.get("text", "").lower()
               for e in events)


def test_plan_tool_absent_without_plan_mode(monkeypatch):
    """`exit_plan_mode` is only offered in plan mode — never in ask/auto turns."""
    _patch_client(monkeypatch)
    tool_sets, state = [], {"n": 0}

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None):
        state["n"] += 1
        tool_sets.append([t["function"]["name"] for t in (tools or [])])
        yield {"type": "delta", "scope": "answer", "text": "hi"}
        yield {"__done__": {"content": "hi", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)
    _drive(agent.run_turn("go", [], None, "m", effort="Low", bash=True,
                          turn_id="t1", permission_mode="ask"))
    assert "exit_plan_mode" not in tool_sets[0]
