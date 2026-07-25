"""Workspace tools flow through run_turn: an edit is gated, approved, applied, and a
file_diff event is emitted."""
import asyncio

import pytest
from app.schemas import AgentTurnRequest
from ocd_core import agent, config, secrets
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


def test_workspace_edit_emits_diff_and_applies(monkeypatch, tmp_path):
    (tmp_path / "a.txt").write_text("old\n")
    calls = iter([
        [_FakeToolCall("c1", "read_file", '{"path": "a.txt"}')],
        [_FakeToolCall("c2", "edit_file", '{"path":"a.txt","old_string":"old","new_string":"new"}')],
        [],
    ])

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        try:
            tcs = next(calls)
        except StopIteration:
            tcs = []
        if tcs:
            yield {"__done__": {"content": "", "note": None, "tool_calls": tcs}}
        else:
            yield {"type": "delta", "scope": "answer", "text": "done"}
            yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    async def scenario():
        events = []
        async for ev in agent.run_turn("edit it", [], None, "m", effort="Low",
                                       workspace_root=str(tmp_path),
                                       permission_mode="acceptEdits", turn_id="t1"):
            events.append(ev)
        return events

    events = asyncio.run(scenario())
    assert (tmp_path / "a.txt").read_text() == "new\n"
    assert any(e.get("type") == "file_diff" for e in events)
    assert any(e.get("type") == "tool_call" for e in events)


def test_workspace_bypass_still_gates_sensitive_builtin(monkeypatch, tmp_path):
    """A workspace turn in bypass must NOT auto-run a sensitive built-in — it falls
    through to the existing HITL (which fails closed here -> approval_required)."""
    calls = iter([[_FakeToolCall("c1", "code_execution", '{"code": "print(1)"}')], []])

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        try:
            tcs = next(calls)
        except StopIteration:
            tcs = []
        if tcs:
            yield {"__done__": {"content": "", "note": None, "tool_calls": tcs}}
        else:
            yield {"type": "delta", "scope": "answer", "text": "done"}
            yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    async def scenario():
        events = []
        # code_exec=True: without enabling it, the H6 "not enabled for this turn" check
        # intercepts the call before it ever reaches the gate under test — verified
        # empirically (and without it, on the PRE-fix gate this call actually executes
        # for real via the docker code-execution engine, no prompt at all).
        async for ev in agent.run_turn("run it", [], None, "m", effort="Low",
                                       workspace_root=str(tmp_path), code_exec=True,
                                       permission_mode="bypass", turn_id="t1"):
            events.append(ev)
        return events

    events = asyncio.run(scenario())
    assert any(e.get("type") == "approval_required" and e.get("name") == "code_execution"
               for e in events)   # gate was NOT skipped for the sensitive built-in


def test_workspace_plan_mode_does_not_hard_deny_safe_tool(monkeypatch, tmp_path):
    """plan mode must not let the workspace gate hard-deny a safe read-only tool
    (web_search); it should fall through to the existing handling (which allows it)."""
    calls = iter([[_FakeToolCall("c1", "web_search", '{"query": "x"}')], []])

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        try:
            tcs = next(calls)
        except StopIteration:
            tcs = []
        if tcs:
            yield {"__done__": {"content": "", "note": None, "tool_calls": tcs}}
        else:
            yield {"type": "delta", "scope": "answer", "text": "done"}
            yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    async def _tool(name, args, tc_id, *a, **k):   # avoid real network
        return {"id": tc_id, "name": name, "ok": True, "result": "ok", "summary": ""}
    monkeypatch.setattr(agent, "_run_one_tool", _tool)

    async def scenario():
        events = []
        # web_search=True: without enabling it, the H6 "not enabled for this turn"
        # check intercepts the call before it ever reaches the harness gate under
        # test, making the assertion below pass vacuously (verified empirically).
        async for ev in agent.run_turn("search", [], None, "m", effort="Low",
                                       workspace_root=str(tmp_path), web_search=True,
                                       permission_mode="plan", turn_id="t1"):
            events.append(ev)
        return events

    events = asyncio.run(scenario())
    assert not any(e.get("type") == "tool_error"
                   and "Blocked by permission rules/mode" in e.get("text", "")
                   for e in events)   # workspace gate did NOT hard-deny web_search


def test_schema_accepts_workspace_id_and_new_modes():
    req = AgentTurnRequest(goal="hi", model="m", workspace_id="abc123",
                           permission_mode="acceptEdits")
    assert req.workspace_id == "abc123"
    # Must round-trip to the EXACT canonical casing ocd_core.harness.rules expects
    # (rules._MODES is case-sensitive) -- a naive .lower() would corrupt this to
    # "acceptedits" and silently fail-closed every acceptEdits-mode turn to strict.
    assert req.permission_mode == "acceptEdits"
    req2 = AgentTurnRequest(goal="hi", model="m", permission_mode="plan")
    assert req2.permission_mode == "plan"


def test_schema_permission_mode_full_contract():
    def mode(v):
        return AgentTurnRequest(goal="hi", model="m", permission_mode=v).permission_mode

    assert mode(None) is None                    # None -> server default, unchanged
    assert mode("default") == "default"
    assert mode("strict") == "strict"
    assert mode("bypass") == "bypass"
    assert mode("auto") == "auto"                 # legacy alias passes through literally
    assert mode("ask") == "ask"                   # legacy alias passes through literally
    assert mode("BYPASS") == "bypass"             # case-insensitive match...
    assert mode("ACCEPTEDITS") == "acceptEdits"   # ...canonical casing preserved
    assert mode("nonsense") == "strict"           # unknown fails closed


_PROTECTED_RULES = {"allow": [], "deny": [], "ask": [], "protected": [".env", "*.pem", "id_*"]}


def _one_call_then_done(tcs):
    calls = iter([tcs, []])

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        try:
            these = next(calls)
        except StopIteration:
            these = []
        if these:
            yield {"__done__": {"content": "", "note": None, "tool_calls": these}}
        else:
            yield {"type": "delta", "scope": "answer", "text": "done"}
            yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    return _fake_stream


def test_workspace_protected_path_prompts_even_in_accept_edits(monkeypatch, tmp_path):
    """Spec S5: a write to a protected path always prompts, even in acceptEdits mode --
    the registry's `protected` globs are wired as generated ask-rules (ask beats the
    acceptEdits mode default, and rules are consulted before mode defaults)."""
    fake_stream = _one_call_then_done(
        [_FakeToolCall("c1", "write_file", '{"path": ".env", "content": "SECRET=1"}')])
    monkeypatch.setattr(agent, "_stream_llm", fake_stream)

    async def scenario():
        events = []
        async for ev in agent.run_turn("write env", [], None, "m", effort="Low",
                                       workspace_root=str(tmp_path),
                                       permission_mode="acceptEdits", turn_id="t1",
                                       workspace_rules=_PROTECTED_RULES):
            events.append(ev)
        return events

    events = asyncio.run(scenario())
    assert any(e.get("type") == "approval_required" and e.get("name") == "write_file"
               for e in events)
    assert not (tmp_path / ".env").exists()   # suspended, not auto-run


def test_workspace_protected_path_prompts_for_nested_file(monkeypatch, tmp_path):
    """The generated ask-rule must catch a protected name at ANY depth, not just the
    workspace root (a bare glob only matches a path with no separators at all)."""
    (tmp_path / "sub").mkdir()
    fake_stream = _one_call_then_done(
        [_FakeToolCall("c1", "write_file", '{"path": "sub/.env", "content": "SECRET=1"}')])
    monkeypatch.setattr(agent, "_stream_llm", fake_stream)

    async def scenario():
        events = []
        async for ev in agent.run_turn("write env", [], None, "m", effort="Low",
                                       workspace_root=str(tmp_path),
                                       permission_mode="acceptEdits", turn_id="t1",
                                       workspace_rules=_PROTECTED_RULES):
            events.append(ev)
        return events

    events = asyncio.run(scenario())
    assert any(e.get("type") == "approval_required" and e.get("name") == "write_file"
               for e in events)
    assert not (tmp_path / "sub" / ".env").exists()


def test_workspace_non_protected_path_auto_runs_in_accept_edits(monkeypatch, tmp_path):
    fake_stream = _one_call_then_done(
        [_FakeToolCall("c1", "write_file", '{"path": "notes.txt", "content": "hi"}')])
    monkeypatch.setattr(agent, "_stream_llm", fake_stream)

    async def scenario():
        events = []
        async for ev in agent.run_turn("write notes", [], None, "m", effort="Low",
                                       workspace_root=str(tmp_path),
                                       permission_mode="acceptEdits", turn_id="t1",
                                       workspace_rules=_PROTECTED_RULES):
            events.append(ev)
        return events

    events = asyncio.run(scenario())
    assert not any(e.get("type") == "approval_required" for e in events)
    assert (tmp_path / "notes.txt").read_text() == "hi"


def test_workspace_bash_passes_root_and_allow(monkeypatch, tmp_path):
    """In a workspace turn, the bash tool calls run_bash with the workspace root,
    the runner allowlist, and the workspace timeout."""
    from ocd_core import config, integrations

    captured = {}

    def _fake_run_bash(command, restart=False, *, root=None, allow=None, timeout=None):
        captured.update(command=command, root=root, allow=allow, timeout=timeout)
        return "ran"

    monkeypatch.setattr(integrations, "run_bash", _fake_run_bash)

    calls = iter([[_FakeToolCall("c1", "bash", '{"command": "pytest -q"}')], []])

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        try:
            tcs = next(calls)
        except StopIteration:
            tcs = []
        if tcs:
            yield {"__done__": {"content": "", "note": None, "tool_calls": tcs}}
        else:
            yield {"type": "delta", "scope": "answer", "text": "done"}
            yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    async def scenario():
        events = []
        async for ev in agent.run_turn("test it", [], None, "m", effort="Low", bash=True,
                                       workspace_root=str(tmp_path),
                                       permission_mode="bypass", turn_id="t1"):
            events.append(ev)
        return events

    asyncio.run(scenario())
    assert captured["root"] == str(tmp_path)
    assert captured["allow"] is integrations.WORKSPACE_BASH_ALLOW
    assert captured["timeout"] == config.WORKSPACE_BASH_TIMEOUT_SEC


def _fake_stream_factory(calls):
    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        try:
            tcs = next(calls)
        except StopIteration:
            tcs = []
        if tcs:
            yield {"__done__": {"content": "", "note": None, "tool_calls": tcs}}
        else:
            yield {"type": "delta", "scope": "answer", "text": "done"}
            yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}
    return _fake_stream


def test_pretooluse_hook_ask_forces_prompt_even_when_mode_allows(monkeypatch, tmp_path):
    """A hook may TIGHTEN (spec §6.4): its "ask" must force the HITL prompt even when the
    rules gate/mode would auto-allow the tool (bypass mode on a workspace file tool)."""
    from ocd_core.harness import hooks

    async def _fake_run(event, payload, cwd=None):
        if event == "PreToolUse":
            return hooks.HookDecision(decision="ask")
        return hooks.HookDecision()

    monkeypatch.setattr(hooks, "run", _fake_run)
    (tmp_path / "a.txt").write_text("old\n")
    calls = iter([[_FakeToolCall("c1", "read_file", '{"path": "a.txt"}')], []])
    monkeypatch.setattr(agent, "_stream_llm", _fake_stream_factory(calls))

    async def scenario():
        return [ev async for ev in agent.run_turn(
            "read it", [], None, "m", effort="Low", workspace_root=str(tmp_path),
            permission_mode="bypass", turn_id="t1")]

    events = asyncio.run(scenario())
    assert any(e.get("type") == "approval_required" and e.get("name") == "read_file"
               for e in events), "hook 'ask' was silently dropped by the rules-gate allow"


def test_pretooluse_hook_denies_tool(monkeypatch, tmp_path):
    """A PreToolUse deny blocks the tool and the model sees the reason."""
    from ocd_core.harness import hooks

    async def _fake_run(event, payload, cwd=None):
        if event == "PreToolUse":
            return hooks.HookDecision(decision="deny", reason="blocked by my gate")
        return hooks.HookDecision()

    monkeypatch.setattr(hooks, "run", _fake_run)
    (tmp_path / "a.txt").write_text("old\n")
    calls = iter([[_FakeToolCall("c1", "read_file", '{"path": "a.txt"}')], []])
    monkeypatch.setattr(agent, "_stream_llm", _fake_stream_factory(calls))

    async def scenario():
        return [ev async for ev in agent.run_turn(
            "read it", [], None, "m", effort="Low", workspace_root=str(tmp_path),
            permission_mode="bypass", turn_id="t1")]

    events = asyncio.run(scenario())
    assert any(e.get("type") == "tool_error" and "blocked by my gate" in e.get("text", "")
               for e in events)


def test_pretooluse_hook_allow_cannot_override_gate_deny(monkeypatch, tmp_path):
    """A hook 'allow' must NOT resurrect a tool the rules gate already denied
    (plan mode denies write_file)."""
    from ocd_core.harness import hooks

    async def _fake_run(event, payload, cwd=None):
        return hooks.HookDecision(decision="allow")

    monkeypatch.setattr(hooks, "run", _fake_run)
    calls = iter([[_FakeToolCall("c1", "write_file", '{"path":"x.txt","content":"y"}')], []])
    monkeypatch.setattr(agent, "_stream_llm", _fake_stream_factory(calls))

    async def scenario():
        return [ev async for ev in agent.run_turn(
            "write it", [], None, "m", effort="Low", workspace_root=str(tmp_path),
            permission_mode="plan", turn_id="t1")]

    events = asyncio.run(scenario())
    assert not (tmp_path / "x.txt").exists()          # never ran
    assert any(e.get("type") == "tool_error" for e in events)


def test_userpromptsubmit_context_reaches_model(monkeypatch, tmp_path):
    from ocd_core.harness import hooks
    seen = {}

    async def _fake_run(event, payload, cwd=None):
        if event == "UserPromptSubmit":
            return hooks.HookDecision(context="REMEMBER-XYZ")
        return hooks.HookDecision()

    monkeypatch.setattr(hooks, "run", _fake_run)

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        seen["messages"] = messages
        yield {"type": "delta", "scope": "answer", "text": "ok"}
        yield {"__done__": {"content": "ok", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    async def scenario():
        return [ev async for ev in agent.run_turn("hi", [], None, "m", effort="Low",
                                                  turn_id="t1")]

    asyncio.run(scenario())
    assert any("REMEMBER-XYZ" in str(m.get("content", "")) for m in seen["messages"])


def test_userpromptsubmit_deny_ends_turn(monkeypatch, tmp_path):
    from ocd_core.harness import hooks

    async def _fake_run(event, payload, cwd=None):
        if event == "UserPromptSubmit":
            return hooks.HookDecision(decision="deny", reason="prompt refused")
        return hooks.HookDecision()

    monkeypatch.setattr(hooks, "run", _fake_run)

    async def _never(*a, **k):
        raise AssertionError("the model must not be called when the prompt is blocked")
        yield {}

    monkeypatch.setattr(agent, "_stream_llm", _never)

    async def scenario():
        return [ev async for ev in agent.run_turn("hi", [], None, "m", effort="Low",
                                                  turn_id="t1")]

    events = asyncio.run(scenario())
    assert any("prompt refused" in str(e.get("text", "")) for e in events)


def test_sessionstart_context_reaches_system_prompt(monkeypatch):
    from ocd_core.harness import hooks
    seen = {}

    async def _fake_run(event, payload, cwd=None):
        if event == "SessionStart":
            return hooks.HookDecision(context="SESSION-MARKER-42")
        return hooks.HookDecision()

    monkeypatch.setattr(hooks, "run", _fake_run)

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        seen["system"] = messages[0]["content"]
        yield {"type": "delta", "scope": "answer", "text": "ok"}
        yield {"__done__": {"content": "ok", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    async def scenario():
        return [ev async for ev in agent.run_turn("hi", [], None, "m", effort="Low",
                                                  turn_id="t1")]

    asyncio.run(scenario())
    assert "SESSION-MARKER-42" in seen["system"]


def test_posttooluse_hook_observes_without_changing_outcome(monkeypatch, tmp_path):
    from ocd_core.harness import hooks
    calls_seen = []

    async def _fake_run(event, payload, cwd=None):
        if event == "PostToolUse":
            calls_seen.append(payload.get("tool_name"))
        return hooks.HookDecision()

    monkeypatch.setattr(hooks, "run", _fake_run)
    (tmp_path / "a.txt").write_text("hello\n")
    calls = iter([[_FakeToolCall("c1", "read_file", '{"path": "a.txt"}')], []])
    monkeypatch.setattr(agent, "_stream_llm", _fake_stream_factory(calls))

    async def scenario():
        return [ev async for ev in agent.run_turn(
            "read it", [], None, "m", effort="Low", workspace_root=str(tmp_path),
            permission_mode="bypass", turn_id="t1")]

    events = asyncio.run(scenario())
    assert "read_file" in calls_seen
    assert any(e.get("type") == "tool_result" for e in events)      # outcome unchanged


def test_stop_hook_fires_once_at_end(monkeypatch):
    from ocd_core.harness import hooks
    fired = []

    async def _fake_run(event, payload, cwd=None):
        if event == "Stop":
            fired.append(event)
        return hooks.HookDecision()

    monkeypatch.setattr(hooks, "run", _fake_run)

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        yield {"type": "delta", "scope": "answer", "text": "ok"}
        yield {"__done__": {"content": "ok", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    async def scenario():
        return [ev async for ev in agent.run_turn("hi", [], None, "m", effort="Low",
                                                  turn_id="t1")]

    asyncio.run(scenario())
    assert fired == ["Stop"]


def test_posttooluse_context_lands_after_tool_replies(monkeypatch, tmp_path):
    """A PostToolUse additionalContext must NOT sit between an assistant's tool_calls
    and its tool replies — that sequence is invalid for real providers."""
    from ocd_core.harness import hooks
    seen = {}

    async def _fake_run(event, payload, cwd=None):
        if event == "PostToolUse":
            return hooks.HookDecision(context="POST-CTX-1")
        return hooks.HookDecision()

    monkeypatch.setattr(hooks, "run", _fake_run)
    (tmp_path / "a.txt").write_text("hello\n")
    calls = iter([[_FakeToolCall("c1", "read_file", '{"path": "a.txt"}')], []])
    inner = _fake_stream_factory(calls)

    async def _spy(llm, model, messages, tools, temperature, max_tokens,
                   content_scope="answer", fallback_model=None, **_kw):
        seen.setdefault("rounds", []).append([dict(m) for m in messages])
        async for ev in inner(llm, model, messages, tools, temperature, max_tokens,
                              content_scope=content_scope, fallback_model=fallback_model):
            yield ev

    monkeypatch.setattr(agent, "_stream_llm", _spy)

    async def scenario():
        return [ev async for ev in agent.run_turn(
            "read it", [], None, "m", effort="Low", workspace_root=str(tmp_path),
            permission_mode="bypass", turn_id="t1")]

    asyncio.run(scenario())
    msgs = seen["rounds"][-1]                      # the round AFTER the tool ran
    roles = [m.get("role") for m in msgs]
    assert "POST-CTX-1" in str(msgs)               # the context did reach the model
    # every tool reply must come before any hook-injected user message
    last_tool = max(i for i, r in enumerate(roles) if r == "tool")
    hook_idx = next(i for i, m in enumerate(msgs)
                    if m.get("role") == "user" and "POST-CTX-1" in str(m.get("content")))
    assert hook_idx > last_tool


def test_posttooluse_receives_tool_input(monkeypatch, tmp_path):
    from ocd_core.harness import hooks
    got = {}

    async def _fake_run(event, payload, cwd=None):
        if event == "PostToolUse":
            got.update(payload)
        return hooks.HookDecision()

    monkeypatch.setattr(hooks, "run", _fake_run)
    (tmp_path / "a.txt").write_text("hello\n")
    calls = iter([[_FakeToolCall("c1", "read_file", '{"path": "a.txt"}')], []])
    monkeypatch.setattr(agent, "_stream_llm", _fake_stream_factory(calls))

    async def scenario():
        return [ev async for ev in agent.run_turn(
            "read it", [], None, "m", effort="Low", workspace_root=str(tmp_path),
            permission_mode="bypass", turn_id="t1")]

    asyncio.run(scenario())
    assert got.get("tool_name") == "read_file"
    assert got.get("tool_input", {}).get("path") == "a.txt"
