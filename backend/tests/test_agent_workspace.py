"""Workspace tools flow through run_turn: an edit is gated, approved, applied, and a
file_diff event is emitted."""
import asyncio

import pytest
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
