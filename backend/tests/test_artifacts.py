"""Phase 3: artifact tool execution + the artifact_open/delta/close event derivation."""
import asyncio

import pytest
from ocd_core import agent, artifact_tools, secrets
from ocd_core.llm import client as llm_client


def test_create_and_update_store():
    store: dict = {}
    a = artifact_tools.create(
        {"title": "Chart", "kind": "html", "content": "<h1>hi</h1>"}, store)
    assert a["id"] == "art1" and a["version"] == 1 and a["kind"] == "html"
    b, err = artifact_tools.update({"id": "art1", "content": "<h1>bye</h1>"}, store)
    assert err is None and b["version"] == 2 and store["art1"]["content"] == "<h1>bye</h1>"
    _, err2 = artifact_tools.update({"id": "nope", "content": "x"}, store)
    assert err2 is not None


def test_unknown_kind_falls_back_to_markdown():
    a = artifact_tools.create({"title": "x", "kind": "banana", "content": "y"}, {})
    assert a["kind"] == "markdown"


def test_csv_is_a_creatable_kind():
    # The model must be able to hand back tabular data as a downloadable table artifact
    # (kind=csv) instead of pasting rows into the chat reply.
    a = artifact_tools.create(
        {"title": "Merged", "kind": "csv", "content": "a,b\n1,2"}, {})
    assert a["kind"] == "csv"
    assert "csv" in artifact_tools.KINDS


def test_completion_events_emit_artifact_triple():
    out = {
        "id": "c1", "name": "create_artifact", "ok": True, "summary": "Chart · html",
        "artifact": {"id": "art1", "title": "Chart", "kind": "html", "language": "",
                     "content": "<h1>hi</h1>", "version": 1},
    }
    evs = agent._completion_events(out)
    types = [e["type"] for e in evs]
    assert types == ["tool_result", "artifact_open", "artifact_delta", "artifact_close"]
    opened = next(e for e in evs if e["type"] == "artifact_open")
    assert opened["title"] == "Chart" and opened["kind"] == "html"
    delta = next(e for e in evs if e["type"] == "artifact_delta")
    assert delta["text"] == "<h1>hi</h1>"


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


class _FakeToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = type("F", (), {"name": name, "arguments": arguments})()

    def model_dump(self):
        return {"id": self.id, "type": "function",
                "function": {"name": self.function.name, "arguments": self.function.arguments}}


def test_run_turn_streams_artifact_events(monkeypatch, _env):
    import json
    state = {"n": 0}

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        state["n"] += 1
        if state["n"] == 1:
            args = json.dumps({"title": "Page", "kind": "html", "content": "<p>x</p>"})
            yield {"__done__": {"content": "", "note": None,
                                "tool_calls": [_FakeToolCall("c1", "create_artifact", args)]}}
        else:
            yield {"type": "delta", "scope": "answer", "text": "Made a page."}
            yield {"__done__": {"content": "Made a page.", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    async def scenario():
        return [ev async for ev in agent.run_turn(
            "make a page", [], None, "m", effort="Low", artifacts=True)]

    types = [e["type"] for e in asyncio.run(scenario())]
    assert "artifact_open" in types and "artifact_delta" in types and "artifact_close" in types


def test_artifacts_off_by_default_in_run_turn(monkeypatch, _env):
    seen = {}

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        seen["tools"] = [t["function"]["name"] for t in (tools or [])]
        yield {"__done__": {"content": "hi", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    async def scenario():
        async for _ in agent.run_turn("hi", [], None, "m", effort="Low"):
            pass
    asyncio.run(scenario())
    assert "create_artifact" not in seen["tools"]
