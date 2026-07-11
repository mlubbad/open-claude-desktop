"""Opik observability tap (ocd_core.opik_tracing).

Contract under test: ``traced()`` is a PASS-THROUGH — every event reaches the
client unchanged whether tracing is off, on, or broken — and, when enabled, the
event stream is mirrored into a trace (tool spans closed by id, thinking spans,
final answer as output, usage as metadata). SDK failures flip a process-wide
latch instead of ever touching the stream. A fake ``opik`` module stands in for
the SDK so no server or real package behavior is involved.
"""
import asyncio
import sys
import types

import pytest
from ocd_core import opik_tracing


class _FakeSpan:
    def __init__(self, **kw):
        self.kw = kw
        self.ended = None

    def end(self, **kw):
        self.ended = kw


class _FakeTrace:
    def __init__(self, **kw):
        self.kw = kw
        self.spans: list[_FakeSpan] = []
        self.ended = None

    def span(self, **kw):
        s = _FakeSpan(**kw)
        self.spans.append(s)
        return s

    def end(self, **kw):
        self.ended = kw


class _FakeOpik:
    instances: list = []

    def __init__(self, **kw):
        self.kw = kw
        self.traces: list[_FakeTrace] = []
        _FakeOpik.instances.append(self)

    def trace(self, **kw):
        t = _FakeTrace(**kw)
        self.traces.append(t)
        return t

    def flush(self, timeout=None):
        return True


@pytest.fixture
def fake_opik(monkeypatch):
    _FakeOpik.instances = []
    fake = types.ModuleType("opik")
    fake.Opik = _FakeOpik
    monkeypatch.setitem(sys.modules, "opik", fake)
    opik_tracing.reset_for_tests()
    yield fake
    opik_tracing.reset_for_tests()


def _enable(monkeypatch):
    monkeypatch.setattr(opik_tracing.settings, "get_settings", lambda: {
        "opik_enabled": True, "opik_url": "http://localhost:5173/api/",
        "opik_project": "test-project"})


def _drive(events):
    async def _gen():
        for ev in events:
            yield ev

    async def _collect():
        return [ev async for ev in opik_tracing.traced(
            _gen(), goal="goal!", model="m", provider="p", effort="Low",
            turn_id="t1", tags=["chat"])]

    return asyncio.run(_collect())


_EVENTS = [
    {"type": "think_open", "phase": "plan"},
    {"type": "delta", "scope": "think", "text": "planning"},
    {"type": "think_close", "elapsed": 1},
    {"type": "answer_open"},
    {"type": "delta", "scope": "answer", "text": "narration"},
    {"type": "answer_to_think", "phase": "narration", "elapsed": 1},
    {"type": "tool", "id": "c1", "name": "web_fetch", "input": "https://x"},
    {"type": "tool_result", "id": "c1", "name": "web_fetch", "summary": "200 OK"},
    {"type": "tool", "id": "c2", "name": "bash", "input": "ls"},
    {"type": "tool_error", "id": "c2", "name": "bash", "text": "declined"},
    {"type": "answer_open"},
    {"type": "delta", "scope": "answer", "text": "final "},
    {"type": "delta", "scope": "answer", "text": "answer"},
    {"type": "usage", "tokens": 123, "cost": 0.01},
]


def test_disabled_is_a_pure_passthrough(monkeypatch):
    """Default settings (opik off): identical events, no client ever constructed."""
    opik_tracing.reset_for_tests()
    monkeypatch.setattr(opik_tracing.settings, "get_settings",
                        lambda: {"opik_enabled": False})
    _FakeOpik.instances = []
    assert _drive(_EVENTS) == _EVENTS
    assert _FakeOpik.instances == []


def test_enabled_mirrors_the_stream_into_a_trace(monkeypatch, fake_opik):
    _enable(monkeypatch)
    out = _drive(_EVENTS)
    assert out == _EVENTS  # the stream is untouched

    client = _FakeOpik.instances[-1]
    assert client.kw["project_name"] == "test-project"
    assert client.kw["host"] == "http://localhost:5173/api/"
    trace = client.traces[0]
    assert trace.kw["input"] == {"goal": "goal!"}
    assert trace.kw["metadata"]["model"] == "m"
    assert "chat" in trace.kw["tags"]

    # think span + two tool spans, each a ONE-SHOT completed record (start+end+output
    # in the creation call — the span()/end() pair risks batching data loss).
    names = [s.kw.get("name") for s in trace.spans]
    assert names == ["think:plan", "web_fetch", "bash"]
    assert all(s.kw.get("start_time") and s.kw.get("end_time") for s in trace.spans)
    assert all(s.ended is None for s in trace.spans)  # never end()ed separately
    ok_span = trace.spans[1]
    assert ok_span.kw["type"] == "tool"
    assert ok_span.kw["input"] == {"input": "https://x"}
    assert ok_span.kw["output"] == {"summary": "200 OK"}
    err_span = trace.spans[2]
    assert err_span.kw["error_info"]["message"] == "declined"

    # The FINAL answer block (not the folded narration) is the trace output,
    # and the usage event lands as metadata.
    assert trace.ended["output"] == {"answer": "final answer"}
    assert trace.ended["metadata"] == {"usage": {"tokens": 123, "cost": 0.01}}


def test_sdk_failure_never_breaks_the_stream(monkeypatch, fake_opik):
    """trace() blowing up flips the latch; every event still reaches the client."""
    _enable(monkeypatch)

    def _boom(**kw):
        raise RuntimeError("clickhouse is down")

    monkeypatch.setattr(_FakeOpik, "trace", lambda self, **kw: _boom(**kw))
    assert _drive(_EVENTS) == _EVENTS
    assert opik_tracing.config() is None  # latched off for the session


def test_span_capture_failure_latches_but_streams_on(monkeypatch, fake_opik):
    _enable(monkeypatch)

    def _boom(self, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(_FakeTrace, "span", _boom)
    assert _drive(_EVENTS) == _EVENTS


def test_interrupted_tool_span_is_closed(monkeypatch, fake_opik):
    """A stream that dies mid-tool still closes the open span and ends the trace."""
    _enable(monkeypatch)
    partial = [
        {"type": "tool", "id": "c1", "name": "bash", "input": "sleep 99"},
        {"type": "error", "text": "provider died"},
    ]
    out = _drive(partial)
    assert out == partial
    trace = _FakeOpik.instances[-1].traces[0]
    assert trace.spans[0].kw["output"] == {"summary": "(interrupted)"}
    assert trace.spans[0].kw["end_time"] is not None
    assert trace.ended["error_info"]["message"] == "provider died"


def test_missing_sdk_no_ops(monkeypatch):
    """opik not importable + enabled: passthrough, latched off, no crash."""
    opik_tracing.reset_for_tests()
    _enable(monkeypatch)
    monkeypatch.setitem(sys.modules, "opik", None)  # import raises
    assert _drive(_EVENTS) == _EVENTS
    assert opik_tracing.config() is None
    opik_tracing.reset_for_tests()


def test_settings_defaults_ship_disabled():
    from ocd_core import config
    assert config.DEFAULT_SETTINGS["opik_enabled"] is False
    assert config.DEFAULT_SETTINGS["opik_project"]
