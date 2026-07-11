"""Step-budget exhaustion — root-cause fixes for the dead-end
"Stopped after the step limit without a final answer."

Previously, exhausting the tool-round budget threw away everything the turn had
gathered and replaced it with a canned error (whose advice — "lower effort" — would
have SHRUNK the budget further). These tests pin the graceful path:

  * the model is warned when the budget is nearly spent (wrap-up note),
  * exhaustion forces one final NO-TOOLS call that synthesizes an answer from the
    gathered material,
  * only if that call itself fails does an (accurate) fallback message appear,
  * a tool call repeated verbatim after failing gets escalating breaker feedback,
    so one broken call can't eat the whole budget,
  * budgets scale with effort (higher effort => MORE rounds).

Driven against the real ``run_turn`` with a fake ``_stream_llm``, mirroring
test_agent_plan_mode.py.
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


def _spy_tools(monkeypatch, executed, ok=True, result="ran"):
    async def _run(name, args, tc_id, *a, **k):
        executed.append(name)
        out = {"id": tc_id, "name": name, "ok": ok, "result": result, "summary": ""}
        if not ok:
            out["error"] = result
        return out
    monkeypatch.setattr(agent, "_run_one_tool", _run)


def _always_tool_calling_stream(calls_log, final_answer="SYNTHESIZED-ANSWER",
                                fail_finalize=False):
    """A model that calls `bash` every round while tools are offered; when tools are
    withheld (the forced finalization call) it answers — or errors, if requested."""
    state = {"n": 0}

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None):
        state["n"] += 1
        calls_log.append({"tools": tools, "messages": [dict(m) for m in messages]})
        if tools is not None:
            yield {"__done__": {"content": "", "note": None, "tool_calls": [
                _FakeToolCall(f"c{state['n']}", "bash", '{"command": "ls"}')]}}
        elif fail_finalize:
            yield {"__done__": {"content": "", "tool_calls": [], "note": "boom",
                                "error": True}}
        else:
            yield {"type": "delta", "scope": "answer", "text": final_answer}
            yield {"__done__": {"content": final_answer, "tool_calls": [], "note": None}}

    return _fake_stream


def test_exhausted_budget_ends_with_synthesized_answer(monkeypatch):
    """Budget exhaustion must end in a real answer built from the gathered material,
    never the canned step-limit error."""
    _patch_client(monkeypatch)
    executed, calls_log = [], []
    _spy_tools(monkeypatch, executed)
    monkeypatch.setattr(agent, "_stream_llm", _always_tool_calling_stream(calls_log))

    events = _drive(agent.run_turn("audit this site", [], None, "m", effort="Low",
                                   bash=True))

    # All budgeted rounds ran the tool…
    assert len(executed) == agent.EFFORT["Low"]["steps"]
    # …then one extra NO-TOOLS call produced the final answer.
    assert calls_log[-1]["tools"] is None
    answer = "".join(e.get("text", "") for e in events
                     if e.get("type") == "delta" and e.get("scope") == "answer")
    assert "SYNTHESIZED-ANSWER" in answer
    assert not any("Stopped after the step limit" in e.get("text", "") for e in events)
    # The finalization call carried the explicit no-more-tools instruction.
    assert any("entire tool budget" in m.get("content", "")
               for m in calls_log[-1]["messages"] if m.get("role") == "user")


def test_wrap_up_warning_lands_before_the_budget_runs_out(monkeypatch):
    """The model is told the budget is nearly spent while it can still act on it."""
    _patch_client(monkeypatch)
    executed, calls_log = [], []
    _spy_tools(monkeypatch, executed)
    monkeypatch.setattr(agent, "_stream_llm", _always_tool_calling_stream(calls_log))

    _drive(agent.run_turn("go", [], None, "m", effort="Low", bash=True))

    steps = agent.EFFORT["Low"]["steps"]
    # Exactly one warning, injected right after the round that leaves
    # WRAP_UP_WARNING_AT rounds remaining — i.e. first visible to the model on
    # round (steps - WRAP_UP_WARNING_AT + 1).
    def _warnings(call):
        return [m for m in call["messages"]
                if m.get("role") == "user" and "tool rounds remain" in m.get("content", "")]
    first_seen = steps - agent.WRAP_UP_WARNING_AT  # 0-based index into calls_log
    assert _warnings(calls_log[first_seen - 1]) == []
    assert len(_warnings(calls_log[first_seen])) == 1
    assert len(_warnings(calls_log[-1])) == 1  # never duplicated later


def test_repeat_fail_breaker_escalates(monkeypatch):
    """The SAME failing call repeated verbatim gets escalating feedback: a corrective
    note on the 2nd failure, a hard STOP from the 3rd on."""
    _patch_client(monkeypatch)
    executed, calls_log = [], []
    _spy_tools(monkeypatch, executed, ok=False, result="ERROR: loc must be a list")
    monkeypatch.setattr(agent, "_stream_llm", _always_tool_calling_stream(calls_log))

    _drive(agent.run_turn("go", [], None, "m", effort="Low", bash=True))

    tool_msgs = [m["content"] for m in calls_log[-1]["messages"]
                 if m.get("role") == "tool"]
    assert len(tool_msgs) == agent.EFFORT["Low"]["steps"]
    assert "Do not repeat it verbatim" not in tool_msgs[0]
    assert "Do not repeat it verbatim" in tool_msgs[1]
    assert all("Do NOT call 'bash'" in t for t in tool_msgs[2:])


def test_distinct_failures_do_not_trip_the_breaker(monkeypatch):
    """Different arguments = legitimate iteration on the error — no breaker note."""
    _patch_client(monkeypatch)
    executed, calls_log, state = [], [], {"n": 0}
    _spy_tools(monkeypatch, executed, ok=False, result="ERROR: nope")

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None):
        state["n"] += 1
        calls_log.append({"tools": tools, "messages": [dict(m) for m in messages]})
        if tools is not None:
            yield {"__done__": {"content": "", "note": None, "tool_calls": [
                _FakeToolCall(f"c{state['n']}", "bash",
                              f'{{"command": "attempt-{state["n"]}"}}')]}}
        else:
            yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)
    _drive(agent.run_turn("go", [], None, "m", effort="Low", bash=True))

    tool_msgs = [m["content"] for m in calls_log[-1]["messages"]
                 if m.get("role") == "tool"]
    assert tool_msgs and all("Do not repeat" not in t and "Do NOT call" not in t
                             for t in tool_msgs)


def test_finalize_failure_falls_back_to_actionable_message(monkeypatch):
    """If even the no-tools synthesis call fails, the fallback text is accurate:
    it offers 'continue' / raising effort — never the old 'lower effort' advice
    (lower effort = a SMALLER budget)."""
    _patch_client(monkeypatch)
    executed, calls_log = [], []
    _spy_tools(monkeypatch, executed)
    monkeypatch.setattr(agent, "_stream_llm",
                        _always_tool_calling_stream(calls_log, fail_finalize=True))

    events = _drive(agent.run_turn("go", [], None, "m", effort="Low", bash=True))

    answer = "".join(e.get("text", "") for e in events
                     if e.get("type") == "delta" and e.get("scope") == "answer")
    assert "continue" in answer and "effort" in answer
    assert "lowering effort" not in answer
    assert "Stopped after the step limit" not in answer


def test_turn_with_answer_never_finalizes(monkeypatch):
    """A turn that answers within budget makes no extra LLM call."""
    _patch_client(monkeypatch)
    calls_log = []

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None):
        calls_log.append({"tools": tools})
        yield {"type": "delta", "scope": "answer", "text": "hi"}
        yield {"__done__": {"content": "hi", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)
    _drive(agent.run_turn("go", [], None, "m", effort="Low"))
    assert len(calls_log) == 1 and calls_log[0]["tools"] is not None


def test_effort_budgets_scale_up_not_down():
    """Guard: budgets must rise with effort, and be sized for real agentic work
    (a browse-N-pages task needs 15+ rounds at High)."""
    order = ["Low", "Medium", "High", "Extra", "Max"]
    budgets = [agent.EFFORT[e]["steps"] for e in order]
    assert budgets == sorted(budgets)
    assert agent.EFFORT["High"]["steps"] >= 16
    assert agent.EFFORT["Low"]["steps"] >= agent.WRAP_UP_WARNING_AT + 1


def test_hitl_decline_never_gets_breaker_advice(monkeypatch):
    """A user DECLINE is a decision, not a tool failure: repeating the call must keep
    the decline message clean — no 'fix the arguments and retry' breaker note that
    would contradict the user."""
    _patch_client(monkeypatch)
    calls_log, state = [], {"n": 0}

    async def _always_decline(turn_id, tc_id, timeout):
        return False
    monkeypatch.setattr(agent.permissions.registry, "wait", _always_decline)

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None):
        state["n"] += 1
        calls_log.append({"tools": tools, "messages": [dict(m) for m in messages]})
        if tools is not None:
            yield {"__done__": {"content": "", "note": None, "tool_calls": [
                _FakeToolCall(f"c{state['n']}", "bash", '{"command": "rm -rf x"}')]}}
        else:
            yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)
    _drive(agent.run_turn("go", [], None, "m", effort="Low", bash=True,
                          turn_id="t1", permission_mode="ask"))

    tool_msgs = [m["content"] for m in calls_log[-1]["messages"]
                 if m.get("role") == "tool"]
    assert tool_msgs and all("DECLINED" in t for t in tool_msgs)
    assert all("Do not repeat it verbatim" not in t and "Do NOT call" not in t
               for t in tool_msgs)


def test_wrap_up_warning_survives_a_blank_round_at_the_threshold(monkeypatch):
    """A blank-answer nudge round exactly at the warning threshold must not silently
    swallow the warning — it lands on the next tool round instead."""
    _patch_client(monkeypatch)
    executed, calls_log, state = [], [], {"n": 0}
    _spy_tools(monkeypatch, executed)
    steps = agent.EFFORT["Low"]["steps"]
    blank_round = steps - agent.WRAP_UP_WARNING_AT  # 1-based: the round that warns

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None):
        state["n"] += 1
        calls_log.append({"tools": tools, "messages": [dict(m) for m in messages]})
        if tools is None:
            yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}
        elif state["n"] == blank_round:
            # Blank round: no content, no tool calls -> the loop nudges and continues.
            yield {"__done__": {"content": "", "tool_calls": [], "note": None}}
        else:
            yield {"__done__": {"content": "", "note": None, "tool_calls": [
                _FakeToolCall(f"c{state['n']}", "bash", '{"command": "ls"}')]}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)
    _drive(agent.run_turn("go", [], None, "m", effort="Low", bash=True))

    warnings = [m for m in calls_log[-1]["messages"]
                if m.get("role") == "user" and "tool rounds remain" in m.get("content", "")]
    assert len(warnings) == 1


def test_distinct_malformed_payloads_get_distinct_breaker_counters(monkeypatch):
    """Two DIFFERENT unparseable argument strings are different attempts — they must
    not share one failure counter (the parsed form of both is {})."""
    _patch_client(monkeypatch)
    executed, calls_log, state = [], [], {"n": 0}
    _spy_tools(monkeypatch, executed, ok=False, result="ERROR: bad args")

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None):
        state["n"] += 1
        calls_log.append({"tools": tools, "messages": [dict(m) for m in messages]})
        if tools is not None:
            yield {"__done__": {"content": "", "note": None, "tool_calls": [
                _FakeToolCall(f"c{state['n']}", "bash", f'{{broken-json-{state["n"]}')]}}
        else:
            yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)
    _drive(agent.run_turn("go", [], None, "m", effort="Low", bash=True))

    tool_msgs = [m["content"] for m in calls_log[-1]["messages"]
                 if m.get("role") == "tool"]
    assert tool_msgs and all("Do not repeat" not in t and "Do NOT call" not in t
                             for t in tool_msgs)


def test_partial_finalize_stream_is_kept_over_the_fallback(monkeypatch):
    """If the finalization stream errors AFTER emitting content, the partial synthesis
    is the answer — not the canned fallback glued onto it."""
    _patch_client(monkeypatch)
    executed, calls_log, state = [], [], {"n": 0}
    _spy_tools(monkeypatch, executed)

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None):
        state["n"] += 1
        calls_log.append({"tools": tools, "messages": [dict(m) for m in messages]})
        if tools is not None:
            yield {"__done__": {"content": "", "note": None, "tool_calls": [
                _FakeToolCall(f"c{state['n']}", "bash", '{"command": "ls"}')]}}
        else:
            yield {"type": "delta", "scope": "answer", "text": "PARTIAL-SYNTHESIS"}
            yield {"__done__": {"content": "PARTIAL-SYNTHESIS", "tool_calls": [],
                                "note": "stream dropped", "error": True}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)
    events = _drive(agent.run_turn("go", [], None, "m", effort="Low", bash=True))

    answer = "".join(e.get("text", "") for e in events
                     if e.get("type") == "delta" and e.get("scope") == "answer")
    assert "PARTIAL-SYNTHESIS" in answer
    assert "step limit" not in answer  # no fallback glued on
