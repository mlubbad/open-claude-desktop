"""Autonomy guardrails — bound a runaway / autonomous run so it can't bill the user's
BYOK key without a ceiling (audit blocker #10).

The EFFORT step cap already bounds a single turn's main loop; these pin the two
amplifiers it doesn't:
  * a per-turn TOKEN BUDGET backstop that lands on a final answer once reported tokens
    cross the ceiling, and
  * a SUBAGENT FAN-OUT cap (each subagent is a full nested turn).

Driven against the real ``run_turn`` with a fake ``_stream_llm``, like
test_agent_step_budget.py.
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


# --- token budget backstop ------------------------------------------------------

def test_token_budget_backstop_stops_early_and_finalizes(monkeypatch):
    """With a tight token budget, the loop stops opening new work well before the step
    cap and lands on the finalize synthesis — the runaway cost ceiling."""
    _patch_client(monkeypatch)
    executed, calls_log, state = [], [], {"n": 0}

    async def _run(name, args, tc_id, *a, **k):
        executed.append(name)
        return {"id": tc_id, "name": name, "ok": True, "result": "ran", "summary": ""}
    monkeypatch.setattr(agent, "_run_one_tool", _run)
    # 1000 output tokens/round; a 2500 budget trips after the 3rd round (3000 >= 2500).
    monkeypatch.setattr(agent.config, "TURN_TOKEN_BUDGET", 2500)

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        state["n"] += 1
        calls_log.append({"tools": tools})
        if tools is not None:
            yield {"__done__": {"content": "", "note": None,
                                "usage": {"prompt_tokens": 0, "completion_tokens": 1000},
                                "tool_calls": [_FakeToolCall(f"c{state['n']}", "bash",
                                                             '{"command": "ls"}')]}}
        else:
            yield {"type": "delta", "scope": "answer", "text": "SYNTH"}
            yield {"__done__": {"content": "SYNTH", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)
    # effort=High would allow 16 rounds; the budget must cut it far shorter.
    events = _drive(agent.run_turn("go", [], None, "m", effort="High", bash=True))

    assert len(executed) == 3                       # stopped 3 rounds in, not 16
    assert calls_log[-1]["tools"] is None           # one no-tools finalize call
    answer = "".join(e.get("text", "") for e in events
                     if e.get("type") == "delta" and e.get("scope") == "answer")
    assert "SYNTH" in answer


def test_token_budget_disabled_runs_full_step_cap(monkeypatch):
    """Budget=0 disables the backstop: the turn runs its full step budget as before."""
    _patch_client(monkeypatch)
    executed, state = [], {"n": 0}

    async def _run(name, args, tc_id, *a, **k):
        executed.append(name)
        return {"id": tc_id, "name": name, "ok": True, "result": "ran", "summary": ""}
    monkeypatch.setattr(agent, "_run_one_tool", _run)
    monkeypatch.setattr(agent.config, "TURN_TOKEN_BUDGET", 0)

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        state["n"] += 1
        if tools is not None:
            yield {"__done__": {"content": "", "note": None,
                                "usage": {"prompt_tokens": 0, "completion_tokens": 999999},
                                "tool_calls": [_FakeToolCall(f"c{state['n']}", "bash",
                                                             '{"command": "ls"}')]}}
        else:
            yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)
    _drive(agent.run_turn("go", [], None, "m", effort="Low", bash=True))
    assert len(executed) == agent.EFFORT["Low"]["steps"]  # full budget, no early stop


# --- subagent fan-out cap -------------------------------------------------------

def test_subagent_fanout_cap_refuses_past_the_limit(monkeypatch):
    """Past the per-turn subagent cap, further spawn_subagent calls are refused with a
    'do it yourself' error instead of launching another nested turn."""
    _patch_client(monkeypatch)
    monkeypatch.setattr(agent.config, "MAX_SUBAGENTS_PER_TURN", 2)
    calls_log, state = [], {"n": 0}

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        names = {t["function"]["name"] for t in tools} if tools else set()
        calls_log.append({"tools": tools, "messages": [dict(m) for m in messages]})
        if "spawn_subagent" in names:          # the top-level turn: keep delegating
            state["n"] += 1
            yield {"__done__": {"content": "", "note": None, "tool_calls": [
                _FakeToolCall(f"c{state['n']}", "spawn_subagent",
                              '{"prompt": "do x", "description": "x"}')]}}
        elif tools is not None:                 # a nested subagent turn: answer cheaply
            yield {"type": "delta", "scope": "answer", "text": "sub done"}
            yield {"__done__": {"content": "sub done", "tool_calls": [], "note": None}}
        else:                                   # top-level finalize (no tools)
            yield {"__done__": {"content": "final", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)
    _drive(agent.run_turn("delegate everything", [], None, "m", effort="Low",
                          subagents=True))

    # The last LLM call is the top-level finalize; its message history carries every
    # spawn_subagent tool result. Past the cap of 2, the result is the refusal.
    tool_results = [m.get("content", "") for m in calls_log[-1]["messages"]
                    if m.get("role") == "tool"]
    capped = [r for r in tool_results if "subagent limit (2)" in r]
    assert capped, tool_results          # the cap actually engaged
    assert any("sub done" in r for r in tool_results)  # the first ones DID run
