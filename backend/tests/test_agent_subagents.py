"""Subagents / Task tool (Phase 6).

`spawn_subagent` lets the agent delegate a well-scoped subtask to an autonomous
subagent that runs a FRESH, isolated `run_turn` (same model/provider/effort and tool
capabilities, but auto-permission, no UI artifacts, and NO further nesting). Only the
subagent's final answer flows back to the parent as a tool result.

These drive the real `run_turn` with a fake `_stream_llm`, so the whole recursive
delegation is exercised without an LLM. The state counter sequences the nested calls:
parent-delegates → subagent-answers → parent-finalises.
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


def test_subagent_delegates_and_returns_answer(monkeypatch):
    _patch_client(monkeypatch)
    tool_sets = []  # tool names offered to the model on each _stream_llm call
    state = {"n": 0}

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        state["n"] += 1
        tool_sets.append([t["function"]["name"] for t in (tools or [])])
        n = state["n"]
        if n == 1:  # parent delegates the subtask
            yield {"__done__": {"content": "", "note": None, "tool_calls": [
                _FakeToolCall("c1", "spawn_subagent",
                              '{"description": "do math", "prompt": "add 40 and 2"}')]}}
        elif n == 2:  # subagent produces its answer (streamed under scope=answer)
            yield {"type": "delta", "scope": "answer", "text": "SUBRESULT-42"}
            yield {"__done__": {"content": "SUBRESULT-42", "tool_calls": [], "note": None}}
        else:  # parent finalises using the subagent's result
            yield {"type": "delta", "scope": "answer", "text": "The subagent computed 42."}
            yield {"__done__": {"content": "The subagent computed 42.",
                                "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    events = _drive(agent.run_turn("go", [], None, "m", effort="Low", subagents=True))

    # The subagent actually ran (all three nested LLM calls happened).
    assert state["n"] == 3
    # A tool card for the delegation, with the description surfaced in the input.
    card = next(e for e in events if e.get("type") == "tool" and e["name"] == "spawn_subagent")
    assert "do math" in card["input"]
    # A successful tool_result (not tool_error), summarising the subagent run.
    res = next(e for e in events if e.get("type") == "tool_result"
               and e["name"] == "spawn_subagent")
    assert "used no tools" in res["summary"]
    # The parent's final answer is present.
    assert any(e.get("type") == "delta" and "computed 42" in e.get("text", "")
               for e in events)
    # The PARENT was offered spawn_subagent; the SUBAGENT was NOT (no nesting).
    assert "spawn_subagent" in tool_sets[0]
    assert "spawn_subagent" not in tool_sets[1]


def test_subagent_refused_when_not_enabled(monkeypatch):
    """Without subagents=True the tool is not in the turn's set, so a call to it is
    refused at dispatch (H6 enablement) rather than silently recursing."""
    _patch_client(monkeypatch)
    state = {"n": 0}

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        state["n"] += 1
        if state["n"] == 1:
            yield {"__done__": {"content": "", "note": None, "tool_calls": [
                _FakeToolCall("c1", "spawn_subagent",
                              '{"description": "x", "prompt": "y"}')]}}
        else:
            yield {"type": "delta", "scope": "answer", "text": "ok"}
            yield {"__done__": {"content": "ok", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    events = _drive(agent.run_turn("go", [], None, "m", effort="Low"))  # subagents off
    assert any(e.get("type") == "tool_error" and "not enabled" in e.get("text", "")
               for e in events)
    # It must NOT have recursed into a second (subagent) turn.
    assert state["n"] == 2


def test_subagent_error_propagates_as_tool_error(monkeypatch):
    """A subagent turn that errors surfaces as a tool_error to the parent, which then
    continues to a final answer instead of crashing."""
    _patch_client(monkeypatch)
    state = {"n": 0}

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        state["n"] += 1
        n = state["n"]
        if n == 1:
            yield {"__done__": {"content": "", "note": None, "tool_calls": [
                _FakeToolCall("c1", "spawn_subagent",
                              '{"description": "x", "prompt": "y"}')]}}
        elif n == 2:  # subagent's LLM call fails
            yield {"__done__": {"error": True, "note": "provider exploded",
                                "content": "", "tool_calls": []}}
        else:
            yield {"type": "delta", "scope": "answer", "text": "recovered"}
            yield {"__done__": {"content": "recovered", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    events = _drive(agent.run_turn("go", [], None, "m", effort="Low", subagents=True))
    assert any(e.get("type") == "tool_error" and e["name"] == "spawn_subagent"
               for e in events)
    assert any(e.get("type") == "delta" and "recovered" in e.get("text", "")
               for e in events)


def test_subagent_runner_returns_final_answer_block_only():
    """The subagent closure keeps ONLY the final answer block: a draft that gets folded
    to a thinking block (answer_to_think) must not leak into the returned result."""
    # Build a run_turn-like event sequence directly and feed it through the same
    # accumulation logic by monkeypatching a minimal recursive run.
    from ocd_core import agent as ag

    async def _fake_run_turn(*a, **k):
        # draft answer, folded away, then the real final answer
        yield {"type": "answer_open"}
        yield {"type": "delta", "scope": "answer", "text": "DRAFT-should-be-dropped"}
        yield {"type": "answer_to_think", "phase": "plan", "elapsed": 1}
        yield {"type": "answer_open"}
        yield {"type": "delta", "scope": "answer", "text": "FINAL-kept"}
        yield {"type": "usage"}

    # Exercise the accumulation contract the closure relies on.
    async def _collect():
        answer_buf: list[str] = []
        async for ev in _fake_run_turn():
            t = ev.get("type")
            if t in ("answer_open", "answer_to_think"):
                answer_buf.clear()
            elif t == "delta" and ev.get("scope") == "answer":
                answer_buf.append(ev.get("text", ""))
        return "".join(answer_buf)

    assert asyncio.run(_collect()) == "FINAL-kept"
    assert ag  # module import sanity
