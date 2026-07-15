"""Parity P0-1/P0-2: project knowledge is reachable in EVERY project chat (not gated
on the BigQuery connector), and attached images ride the user message as multimodal
content parts.
"""
import asyncio

import pytest
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


def _wire(monkeypatch, captured):
    """Fake the LLM: first round calls search_project_knowledge, then answers.
    Captures the tools + messages given to the model."""
    monkeypatch.setattr(agent, "resolve_turn_client",
                        lambda model, provider=None: (object(), model, None))
    monkeypatch.setattr(agent.schema_catalog, "ensure_catalog", lambda: None)
    state = {"n": 0}

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        state["n"] += 1
        captured.setdefault("tools", [t["function"]["name"] for t in tools])
        captured.setdefault("messages", messages)
        if state["n"] == 1:
            yield {"__done__": {"content": "", "note": None,
                                "tool_calls": [_FakeToolCall(
                                    "c1", "search_project_knowledge",
                                    '{"question": "what does the report say?"}')]}}
        else:
            yield {"type": "delta", "scope": "answer", "text": "done"}
            yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)


def test_kb_tool_offered_and_dispatched_without_bigquery(monkeypatch):
    """A default install (no BigQuery) with a project active can search its KB."""
    captured: dict = {}
    _wire(monkeypatch, captured)
    assert not agent.bigquery_tools.enabled()

    calls = {}

    def _fake_search(project_id, question, top_k):
        calls.update(project=project_id, question=question, top_k=top_k)
        return "[report.pdf · chunk 3]\nRevenue grew 12%."

    monkeypatch.setattr("ocd_core.knowledge.search_project_kb", _fake_search)

    events = _drive(agent.run_turn("hi", [], "proj-1", "m", effort="Low"))

    assert "search_project_knowledge" in captured["tools"]
    assert calls == {"project": "proj-1", "question": "what does the report say?",
                     "top_k": 6}
    result = next(e for e in events if e.get("type") == "tool_result")
    assert "passage" in result["summary"]


def test_kb_tool_not_offered_without_a_project(monkeypatch):
    """General (no-project) chats have no KB — the tool isn't in the set, and a
    hallucinated call is refused at dispatch (H6)."""
    captured: dict = {}
    _wire(monkeypatch, captured)
    events = _drive(agent.run_turn("hi", [], None, "m", effort="Low"))
    assert "search_project_knowledge" not in captured["tools"]
    assert any(e.get("type") == "tool_error" and "not enabled" in e.get("text", "")
               for e in events)


def test_kb_empty_returns_a_graceful_no_match(monkeypatch):
    """An empty/unmatched KB is a normal outcome, not an error the model retries."""
    captured: dict = {}
    _wire(monkeypatch, captured)
    monkeypatch.setattr("ocd_core.knowledge.search_project_kb",
                        lambda project_id, question, top_k: "")
    events = _drive(agent.run_turn("hi", [], "proj-1", "m", effort="Low"))
    result = next(e for e in events if e.get("type") == "tool_result")
    assert result["summary"] == "no matches"


def test_vision_model_gets_images_as_multimodal_parts(monkeypatch):
    """P0-2: for a VISION-capable model, data-URI images become OpenAI-style content parts
    on THIS turn's user message; without images the content stays a plain string."""
    captured: dict = {}
    _wire(monkeypatch, captured)
    uri = "data:image/png;base64,iVBORw0KGgo="
    _drive(agent.run_turn("what is in this picture?", [], None, "gpt-4o",
                          effort="Low", images=[uri]))
    user = next(m for m in captured["messages"] if m["role"] == "user")
    assert isinstance(user["content"], list)
    assert user["content"][0] == {"type": "text", "text": "what is in this picture?"}
    assert user["content"][1] == {"type": "image_url", "image_url": {"url": uri}}

    captured2: dict = {}
    _wire(monkeypatch, captured2)
    _drive(agent.run_turn("plain", [], None, "gpt-4o", effort="Low"))
    user2 = next(m for m in captured2["messages"] if m["role"] == "user")
    assert user2["content"] == "plain"


def test_text_only_model_gets_images_described_as_text(monkeypatch):
    """A text-only model can't take vision parts, so attached images are described by a
    configured vision model and injected as TEXT (root-cause fix for 'I can't see the
    image'). The content stays a plain string the model can actually read."""
    captured: dict = {}
    _wire(monkeypatch, captured)
    monkeypatch.setattr(agent.vision, "image_context",
                        lambda imgs: "[image content: a bar chart of monthly revenue]")
    uri = "data:image/png;base64,iVBORw0KGgo="
    _drive(agent.run_turn("build this table", [], None, "m", effort="Low", images=[uri]))
    user = next(m for m in captured["messages"] if m["role"] == "user")
    assert isinstance(user["content"], str)
    assert "build this table" in user["content"]
    assert "bar chart of monthly revenue" in user["content"]


def test_kb_search_is_read_only_safe():
    """A local vector search over the user's own documents must never prompt for
    approval in 'ask' mode — it is the same class as search_schema/web_search."""
    from ocd_core import permissions
    assert permissions.is_sensitive("search_project_knowledge") is False
    assert permissions.requires_approval("search_project_knowledge", "ask") is False


def test_project_memory_reaches_the_system_prompt(monkeypatch):
    """P0-4: the stored project memory becomes a system-prompt section."""
    captured: dict = {}
    _wire(monkeypatch, captured)
    _drive(agent.run_turn("hi", [], "p", "m", effort="Low",
                          project_memory="Ali prefers tables."))
    system = captured["messages"][0]
    assert system["role"] == "system"
    assert "PROJECT MEMORY" in system["content"]
    assert "Ali prefers tables." in system["content"]


def test_turn_request_bounds_images():
    """The API schema rejects unbounded/foreign image payloads."""
    from app.schemas import MAX_IMAGES, AgentTurnRequest

    ok = AgentTurnRequest(goal="g", model="m",
                          images=["data:image/png;base64,AAAA"])
    assert len(ok.images) == 1

    with pytest.raises(ValueError):
        AgentTurnRequest(goal="g", model="m",
                         images=["data:image/png;base64,A"] * (MAX_IMAGES + 1))
    with pytest.raises(ValueError):
        AgentTurnRequest(goal="g", model="m", images=["https://evil.example/x.png"])
