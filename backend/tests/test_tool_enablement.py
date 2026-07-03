"""Phase 0 (H6): a tool not enabled for the turn is refused at DISPATCH.

Enablement previously gated only which tool schemas were sent to the model, so a
hallucinated or injected tool call still reached the dispatcher. run_turn now
executes only names present in the turn's assembled tool set.
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


def test_disallowed_tool_is_not_dispatched(monkeypatch):
    monkeypatch.setattr(agent, "resolve_turn_client",
                        lambda model, provider=None: (object(), model, None))
    monkeypatch.setattr(agent.schema_catalog, "ensure_catalog", lambda: None)

    executed = []

    async def _boom(name, args, tc_id, *a, **k):
        executed.append(name)
        return {"id": tc_id, "name": name, "ok": True, "result": "ran", "summary": ""}

    monkeypatch.setattr(agent, "_run_one_tool", _boom)

    state = {"n": 0}

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None):
        state["n"] += 1
        if state["n"] == 1:
            # The model "calls" a tool that was never offered this turn.
            yield {"__done__": {"content": "", "note": None,
                                "tool_calls": [_FakeToolCall("c1", "evil_tool", "{}")]}}
        else:
            yield {"type": "delta", "scope": "answer", "text": "done"}
            yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    events = _drive(agent.run_turn("hi", [], None, "m", effort="Low"))

    # The bogus tool must NOT have executed...
    assert "evil_tool" not in executed
    # ...and the stream must carry a tool_error explaining it wasn't enabled.
    assert any(e.get("type") == "tool_error" and "not enabled" in e.get("text", "")
               for e in events)
    # The turn still completes with the final answer.
    assert any(e.get("type") == "delta" and e.get("text") == "done" for e in events)


def test_allowed_builtin_tool_still_dispatches(monkeypatch):
    monkeypatch.setattr(agent, "resolve_turn_client",
                        lambda model, provider=None: (object(), model, None))
    monkeypatch.setattr(agent.schema_catalog, "ensure_catalog", lambda: None)

    executed = []

    async def _ok(name, args, tc_id, *a, **k):
        executed.append(name)
        return {"id": tc_id, "name": name, "ok": True,
                "result": "schema...", "summary": "1 table"}

    monkeypatch.setattr(agent, "_run_one_tool", _ok)

    state = {"n": 0}

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None):
        state["n"] += 1
        if state["n"] == 1:
            # search_schema is a built-in always in the tool set -> must dispatch.
            yield {"__done__": {"content": "", "note": None,
                                "tool_calls": [_FakeToolCall("c1", "search_schema",
                                                             '{"question": "x"}')]}}
        else:
            yield {"type": "delta", "scope": "answer", "text": "done"}
            yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    _drive(agent.run_turn("hi", [], None, "m", effort="Low"))
    assert "search_schema" in executed
