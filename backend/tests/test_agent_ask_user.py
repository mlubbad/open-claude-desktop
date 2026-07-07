"""ask_user through run_turn: a structured clarifying question ends the turn with a
`question` event; invalid payloads feed an error back instead; the tool is only
offered on interactive turns (turn_id present)."""
import asyncio
import json

import pytest
from ocd_core import agent, secrets
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
    yield
    secrets.reset_store()
    llm_client.reset_clients()


VALID_ARGS = json.dumps({"questions": [
    {"title": "Which channel is this for?",
     "options": ["Tech channel", "Systems channel", "Something else"]},
    {"title": "How long?", "options": ["Short", "Long"], "allow_other": False},
]})


def _drive(monkeypatch, arguments: str, turn_id="t1", second_call=None):
    """Run a turn whose model first calls ask_user with `arguments`; the optional
    second stream response lets invalid-payload turns recover to a plain answer."""
    state = {"n": 0, "tools_sent": []}

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None):
        state["n"] += 1
        state["tools_sent"].append([t["function"]["name"] for t in (tools or [])])
        if state["n"] == 1:
            yield {"__done__": {"content": "", "note": None,
                                "tool_calls": [_FakeToolCall("q1", "ask_user", arguments)]}}
        else:
            yield {"type": "delta", "scope": "answer", "text": second_call or "done"}
            yield {"__done__": {"content": second_call or "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    async def scenario():
        events = []
        async for ev in agent.run_turn("write a script", [], None, "m", effort="Low",
                                       turn_id=turn_id, permission_mode="ask"):
            events.append(ev)
        return events, state

    return asyncio.run(scenario())


def test_ask_user_emits_question_and_ends_turn(monkeypatch):
    events, state = _drive(monkeypatch, VALID_ARGS)
    types = [e["type"] for e in events]
    q = next(e for e in events if e["type"] == "question")
    assert q["id"] == "q1"
    assert [x["title"] for x in q["questions"]] == ["Which channel is this for?", "How long?"]
    assert q["questions"][0]["allow_other"] is True   # defaults on
    assert q["questions"][1]["allow_other"] is False
    # The turn ended right after the question: no further stream round, no answer.
    assert state["n"] == 1
    assert types.index("question") == len(types) - 1
    # The tool card completed before the question.
    tr = next(e for e in events if e["type"] == "tool_result" and e["id"] == "q1")
    assert "answer" in tr["summary"].lower()
    # The tool was offered to the model on this interactive turn.
    assert "ask_user" in state["tools_sent"][0]


def test_invalid_payload_feeds_error_back_and_turn_continues(monkeypatch):
    events, state = _drive(monkeypatch, json.dumps({"questions": [{"title": "?", "options": ["only-one"]}]}))
    types = [e["type"] for e in events]
    assert "question" not in types
    err = next(e for e in events if e["type"] == "tool_error" and e["id"] == "q1")
    assert "Invalid" in err["text"]
    # The model got a second round and produced a normal answer.
    assert state["n"] == 2
    assert any(e["type"] == "delta" and e.get("scope") == "answer" for e in events)


def test_ask_user_not_offered_without_turn_id(monkeypatch):
    """Autonomous runs (cowork/scheduler/subagents pass no turn_id) must not get the
    tool, and a hallucinated call is refused by the enablement gate."""
    state = {"n": 0, "tools_sent": []}

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None):
        state["n"] += 1
        state["tools_sent"].append([t["function"]["name"] for t in (tools or [])])
        if state["n"] == 1:
            yield {"__done__": {"content": "", "note": None,
                                "tool_calls": [_FakeToolCall("q1", "ask_user", VALID_ARGS)]}}
        else:
            yield {"type": "delta", "scope": "answer", "text": "done"}
            yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    async def scenario():
        events = []
        async for ev in agent.run_turn("goal", [], None, "m", effort="Low"):
            events.append(ev)
        return events

    events = asyncio.run(scenario())
    assert "ask_user" not in state["tools_sent"][0]
    assert not any(e["type"] == "question" for e in events)
    err = next(e for e in events if e["type"] == "tool_error" and e["id"] == "q1")
    assert "not enabled" in err["text"]


def test_parse_questions_bounds_and_validates():
    # Only the first 3 entries are considered; within them, blank titles, <2-option
    # lists, and empty option strings are dropped; options cap at 5.
    args = {"questions": [
        {"title": "A", "options": ["1", "2", "3", "4", "5", "6", "7"]},
        {"title": "  ", "options": ["x", "y"]},   # blank title → dropped
        {"title": "B", "options": ["only"]},      # <2 options → dropped
        {"title": "D", "options": ["x", "y"]},    # 4th entry → beyond the cap, ignored
    ]}
    out = agent.parse_questions(args)
    assert [q["title"] for q in out] == ["A"]
    assert len(out[0]["options"]) == 5            # capped at 5

    # Four valid questions cap to three.
    many = {"questions": [{"title": t, "options": ["x", "y"]} for t in "ABCD"]}
    assert [q["title"] for q in agent.parse_questions(many)] == ["A", "B", "C"]

    # Empty option strings are removed; still valid with 2 left.
    mixed = agent.parse_questions({"questions": [{"title": "C", "options": ["x", "", "y"]}]})
    assert mixed[0]["options"] == ["x", "y"]

    assert agent.parse_questions({}) == []
    assert agent.parse_questions({"questions": "nope"}) == []
