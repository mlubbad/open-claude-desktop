"""Live artifact streaming through _stream_llm: as create_artifact tool-call arguments
arrive in fragments, artifact_open/artifact_delta events are emitted live, and the
completion suppresses the repeat open + full delta for the already-streamed artifact."""
import asyncio
import types

from ocd_core import agent, artifact_tools


def _tc(index, tid=None, name=None, args=None):
    return types.SimpleNamespace(index=index, id=tid,
                                 function=types.SimpleNamespace(name=name, arguments=args))


def _chunk(*tool_calls, content=None):
    delta = types.SimpleNamespace(content=content, tool_calls=list(tool_calls) or None)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(delta=delta)])


async def _fake_chunks(*_a, **_k):
    # A create_artifact tool call whose JSON arguments arrive across four fragments.
    yield _chunk(_tc(0, tid="callX", name="create_artifact", args='{"title":"Doc",'))
    yield _chunk(_tc(0, args='"kind":"markdown","content":"Hel'))
    yield _chunk(_tc(0, args='lo wor'))
    yield _chunk(_tc(0, args='ld"}'))


def _collect(events_coro):
    return asyncio.run(events_coro)


def test_stream_llm_emits_live_artifact_events(monkeypatch):
    monkeypatch.setattr(agent, "_stream_chunks", _fake_chunks)

    async def run():
        out = []
        async for ev in agent._stream_llm(None, "m", [], tools=[]):
            out.append(ev)
        return out

    evs = _collect(run())
    opens = [e for e in evs if e.get("type") == "artifact_open"]
    deltas = [e for e in evs if e.get("type") == "artifact_delta"]
    done = next(e["__done__"] for e in evs if "__done__" in e)

    assert len(opens) == 1
    assert opens[0]["id"] == "callX"
    assert opens[0]["title"] == "Doc"
    assert opens[0]["kind"] == "markdown"
    # Content streamed in pieces, reassembled in order.
    assert "".join(d["text"] for d in deltas) == "Hello world"
    assert all(d["id"] == "callX" for d in deltas)
    # The tool call is still fully assembled for execution, and flagged as streamed.
    assert done["tool_calls"][0].id == "callX"
    assert "callX" in done["streamed_artifacts"]


def test_completion_events_suppresses_streamed_artifact():
    out = {"id": "callX", "name": "create_artifact", "ok": True, "summary": "x",
           "artifact": {"id": "callX", "title": "Doc", "kind": "markdown",
                        "content": "Hello world", "version": 1}}
    # Streamed live → only a close (no repeat open + full-content delta).
    streamed = [e["type"] for e in agent._completion_events(out, {"callX"})]
    assert "artifact_open" not in streamed
    assert "artifact_delta" not in streamed
    assert "artifact_close" in streamed
    # Not streamed → the whole artifact is emitted at completion.
    full = [e["type"] for e in agent._completion_events(out, set())]
    assert full.count("artifact_open") == 1
    assert "artifact_delta" in full and "artifact_close" in full


def test_create_honors_explicit_id():
    store: dict = {}
    a = artifact_tools.create({"title": "T", "kind": "html", "content": "x"}, store,
                              artifact_id="callX")
    assert a["id"] == "callX"
    assert store["callX"]["content"] == "x"
    # Default path still uses the counter.
    b = artifact_tools.create({"title": "U", "kind": "html", "content": "y"}, store)
    assert b["id"].startswith("art")
