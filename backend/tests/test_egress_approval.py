"""First-contact domain approval for `web_fetch` + the egress audit trail.

Part 1: direct unit tests for `ocd_core.egress_policy` (outbound_host parsing +
the per-project approval registry) — no agent loop involved.

Part 2: end-to-end tests through `agent.run_turn`, mirroring the harness in
test_agent_hitl.py, proving:
  * the FIRST `web_fetch` call to a brand-new host suspends for approval via the
    EXISTING HITL `approval_required` / `permissions.registry` flow (no new event
    type, no new route);
  * once approved, the host is remembered PER PROJECT, so a SECOND, separate turn
    (different turn_id, same project, empty history) against the same host does
    NOT re-prompt;
  * a decline blocks the tool (never runs it) and feeds the model a fixed
    "do not retry" message instead.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from ocd_core import agent, config, egress_policy, permissions, secrets
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
    egress_policy.registry.reset()
    monkeypatch.setattr(agent, "resolve_turn_client",
                        lambda model, provider=None: (object(), model, None))
    monkeypatch.setattr(agent.schema_catalog, "ensure_catalog", lambda: None)
    monkeypatch.setattr(config, "PERMISSION_TIMEOUT_SEC", 2)
    yield
    egress_policy.registry.reset()
    secrets.reset_store()
    llm_client.reset_clients()


# --------------------------------------------------------------------------- #
# Part 1 — egress_policy unit tests
# --------------------------------------------------------------------------- #

def test_outbound_host_returns_lowercased_host_for_web_fetch():
    assert egress_policy.outbound_host(
        "web_fetch", {"url": "https://Example.COM/path?x=1"}) == "example.com"


def test_outbound_host_strips_a_trailing_dot():
    assert egress_policy.outbound_host(
        "web_fetch", {"url": "https://example.com./x"}) == "example.com"


def test_outbound_host_none_for_non_web_fetch_tools():
    # Only web_fetch is domain-gated -- search/MCP/connectors must never match.
    assert egress_policy.outbound_host("bash", {"url": "https://example.com/x"}) is None
    assert egress_policy.outbound_host("web_search", {"query": "example.com"}) is None
    assert egress_policy.outbound_host("run_sql", {}) is None
    assert egress_policy.outbound_host("mcp_github_create_issue", {"url": "https://x.com"}) is None


@pytest.mark.parametrize("args", [
    {}, {"url": ""}, {"url": "   "}, {"url": "not-a-url"}, {"url": "/just/a/path"},
])
def test_outbound_host_none_for_missing_or_unparseable_url(args):
    assert egress_policy.outbound_host("web_fetch", args) is None


def test_outbound_host_handles_none_args():
    assert egress_policy.outbound_host("web_fetch", None) is None


def test_registry_approval_is_scoped_per_project():
    reg = egress_policy.EgressApprovalRegistry()
    assert reg.is_approved("proj-a", "example.com") is False
    reg.approve("proj-a", "example.com")
    assert reg.is_approved("proj-a", "example.com") is True
    # Approving in project A must NOT approve the same host in project B.
    assert reg.is_approved("proj-b", "example.com") is False


def test_registry_none_project_key_is_a_stable_shared_bucket():
    reg = egress_policy.EgressApprovalRegistry()
    reg.approve(None, "example.com")
    assert reg.is_approved(None, "example.com") is True
    # A concrete project id is still isolated from the "no project" bucket.
    assert reg.is_approved("proj-a", "example.com") is False


def test_registry_reset_clears_every_project():
    reg = egress_policy.EgressApprovalRegistry()
    reg.approve("proj-a", "example.com")
    reg.approve(None, "other.example")
    reg.reset()
    assert reg.is_approved("proj-a", "example.com") is False
    assert reg.is_approved(None, "other.example") is False


# --------------------------------------------------------------------------- #
# Part 2 — the gate inside agent.run_turn
# --------------------------------------------------------------------------- #

def _fake_stream_one_web_fetch(url, tc_id, seen_messages=None):
    """Round 1: the model calls web_fetch(url). Every later round: final answer.

    If `seen_messages` is a list, the `messages` argument passed to EVERY call is
    appended to it, so a test can inspect what the model was told about a blocked
    call (round 2's tool-role message for tc_id).
    """
    state = {"n": 0}

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        if seen_messages is not None:
            seen_messages.append(messages)
        state["n"] += 1
        if state["n"] == 1:
            yield {"__done__": {"content": "", "note": None,
                                "tool_calls": [_FakeToolCall(
                                    tc_id, "web_fetch", json.dumps({"url": url}))]}}
        else:
            yield {"type": "delta", "scope": "answer", "text": "done"}
            yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    return _fake_stream


async def _resolve_when_pending(turn_id, tc_id, decision):
    for _ in range(400):
        if permissions.registry.pending(turn_id):
            permissions.registry.resolve(turn_id, tc_id, decision)
            return
        await asyncio.sleep(0.005)


def test_first_contact_prompts_second_contact_is_remembered_per_project(monkeypatch):
    project = "proj-1"
    host = "new.example"
    url = f"https://{host}/x"
    executed = []

    async def _tool(name, args, tc_id, *a, **k):
        executed.append((name, args.get("url")))
        return {"id": tc_id, "name": name, "ok": True, "result": "fetched", "summary": ""}

    monkeypatch.setattr(agent, "_run_one_tool", _tool)

    # --- Turn 1: first contact with `host` -> must suspend for approval.
    monkeypatch.setattr(agent, "_stream_llm", _fake_stream_one_web_fetch(url, "c1"))

    async def scenario_1():
        events = []
        task = asyncio.create_task(_resolve_when_pending("t1", "c1", True))
        async for ev in agent.run_turn("fetch it", [], project, "m", effort="Low",
                                       web_fetch=True, turn_id="t1", permission_mode="ask"):
            events.append(ev)
        await task
        return events

    events_1 = asyncio.run(scenario_1())
    types_1 = [e["type"] for e in events_1]
    assert "approval_required" in types_1
    ar = next(e for e in events_1 if e["type"] == "approval_required")
    assert ar["id"] == "c1" and ar["turn_id"] == "t1" and ar["name"] == "web_fetch"
    assert host in ar.get("reason", "")  # first-contact prompt names the host
    assert ("web_fetch", url) in executed  # approved -> the tool actually ran
    assert egress_policy.registry.is_approved(project, host) is True

    # --- Turn 2: SAME project, SAME host, a DIFFERENT turn, EMPTY history ->
    # proves the memory is project-scoped, not conversation-scoped.
    monkeypatch.setattr(agent, "_stream_llm", _fake_stream_one_web_fetch(url, "c2"))

    async def scenario_2():
        events = []
        async for ev in agent.run_turn("fetch it again", [], project, "m", effort="Low",
                                       web_fetch=True, turn_id="t2", permission_mode="ask"):
            events.append(ev)
        return events

    events_2 = asyncio.run(scenario_2())
    types_2 = [e["type"] for e in events_2]
    assert "approval_required" not in types_2  # per-project memory: no re-prompt
    assert executed.count(("web_fetch", url)) == 2  # ran again, without prompting


def test_first_contact_in_one_project_does_not_approve_another(monkeypatch):
    host = "shared.example"
    url = f"https://{host}/x"
    executed = []

    async def _tool(name, args, tc_id, *a, **k):
        executed.append(name)
        return {"id": tc_id, "name": name, "ok": True, "result": "fetched", "summary": ""}

    monkeypatch.setattr(agent, "_run_one_tool", _tool)
    monkeypatch.setattr(agent, "_stream_llm", _fake_stream_one_web_fetch(url, "c1"))

    async def scenario_1():
        events = []
        task = asyncio.create_task(_resolve_when_pending("t1", "c1", True))
        async for ev in agent.run_turn("fetch it", [], "proj-a", "m", effort="Low",
                                       web_fetch=True, turn_id="t1", permission_mode="ask"):
            events.append(ev)
        await task
        return events

    asyncio.run(scenario_1())
    assert egress_policy.registry.is_approved("proj-a", host) is True

    # A different project, same host -> must prompt again.
    monkeypatch.setattr(agent, "_stream_llm", _fake_stream_one_web_fetch(url, "c2"))

    async def scenario_2():
        events = []
        task = asyncio.create_task(_resolve_when_pending("t2", "c2", True))
        async for ev in agent.run_turn("fetch it", [], "proj-b", "m", effort="Low",
                                       web_fetch=True, turn_id="t2", permission_mode="ask"):
            events.append(ev)
        await task
        return events

    events_2 = asyncio.run(scenario_2())
    types_2 = [e["type"] for e in events_2]
    assert "approval_required" in types_2  # NOT remembered cross-project


def test_denied_domain_blocks_the_tool_and_is_not_retried(monkeypatch):
    project = "proj-2"
    host = "blocked.example"
    url = f"https://{host}/y"
    executed = []
    seen_messages = []

    async def _tool(name, args, tc_id, *a, **k):
        executed.append(name)
        return {"id": tc_id, "name": name, "ok": True, "result": "fetched", "summary": ""}

    monkeypatch.setattr(agent, "_run_one_tool", _tool)
    monkeypatch.setattr(agent, "_stream_llm",
                        _fake_stream_one_web_fetch(url, "c1", seen_messages=seen_messages))

    async def scenario():
        events = []
        task = asyncio.create_task(_resolve_when_pending("t1", "c1", False))
        async for ev in agent.run_turn("fetch it", [], project, "m", effort="Low",
                                       web_fetch=True, turn_id="t1", permission_mode="ask"):
            events.append(ev)
        await task
        return events

    events = asyncio.run(scenario())
    types = [e["type"] for e in events]
    assert "approval_required" in types
    assert "web_fetch" not in executed  # declined -> never executed
    err = next(e for e in events if e["type"] == "tool_error" and e["id"] == "c1")
    assert host in err["text"]
    assert egress_policy.registry.is_approved(project, host) is False

    # The model is told NOT to retry that host -- fed back on round 2's messages.
    assert len(seen_messages) >= 2
    tool_msgs = [m for m in seen_messages[1]
                if isinstance(m, dict) and m.get("tool_call_id") == "c1"]
    assert tool_msgs, "expected a tool-role message for c1 in round 2"
    assert "did NOT approve" in tool_msgs[0]["content"]
    assert host in tool_msgs[0]["content"]


def test_auto_mode_auto_approves_and_remembers_without_prompting(monkeypatch):
    # No turn_id at all -> gate_on is False -> auto-approve, but still recorded.
    project = "proj-3"
    host = "auto.example"
    url = f"https://{host}/z"
    executed = []

    async def _tool(name, args, tc_id, *a, **k):
        executed.append(name)
        return {"id": tc_id, "name": name, "ok": True, "result": "fetched", "summary": ""}

    monkeypatch.setattr(agent, "_run_one_tool", _tool)
    monkeypatch.setattr(agent, "_stream_llm", _fake_stream_one_web_fetch(url, "c1"))

    async def scenario():
        events = []
        async for ev in agent.run_turn("fetch it", [], project, "m", effort="Low",
                                       web_fetch=True):
            events.append(ev)
        return events

    events = asyncio.run(scenario())
    types = [e["type"] for e in events]
    assert "approval_required" not in types
    assert "web_fetch" in executed
    assert egress_policy.registry.is_approved(project, host) is True
