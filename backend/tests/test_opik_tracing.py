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


def _enable(monkeypatch, **over):
    base = {"opik_enabled": True, "opik_mode": "local",
            "opik_url": "http://localhost:5173/api/", "opik_project": "test-project"}
    base.update(over)
    monkeypatch.setattr(opik_tracing.settings, "get_settings", lambda: base)
    # No stored/env key unless a test opts in — keeps mode inference deterministic.
    monkeypatch.setattr(opik_tracing, "api_key", lambda: over.get("_key"))


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
    assert config.DEFAULT_SETTINGS["opik_mode"] == "local"


def test_cloud_mode_targets_comet_with_the_keychain_key(monkeypatch, fake_opik):
    """Cloud mode sends to comet.com with the stored API key + workspace, no self-host URL."""
    _enable(monkeypatch, opik_mode="cloud", opik_workspace="my-ws", _key="sk-opik-123")
    _drive(_EVENTS)
    client = _FakeOpik.instances[-1]
    assert client.kw["host"] == opik_tracing.OPIK_URL_CLOUD
    assert client.kw["api_key"] == "sk-opik-123"
    assert client.kw["workspace"] == "my-ws"


def test_local_mode_needs_no_key_and_uses_the_url(monkeypatch, fake_opik):
    _enable(monkeypatch, opik_mode="local", opik_url="http://host:5173/api/")
    _drive(_EVENTS)
    client = _FakeOpik.instances[-1]
    assert client.kw["host"] == "http://host:5173/api/"
    assert client.kw["api_key"] is None and client.kw["workspace"] is None


def test_mode_comes_from_settings_only(monkeypatch):
    """No inference, no env re-reads: the clamped opik_mode setting decides. (The old
    guess-from-key-presence branch was deleted when settings gained enum clamping.)"""
    monkeypatch.setattr(opik_tracing, "api_key", lambda: "sk-1")
    monkeypatch.setattr(opik_tracing.settings, "get_settings",
                        lambda: {"opik_enabled": True, "opik_mode": "cloud"})
    assert opik_tracing.config()["mode"] == "cloud"
    # Even with a key present, an explicit local mode stays local.
    monkeypatch.setattr(opik_tracing.settings, "get_settings",
                        lambda: {"opik_enabled": True, "opik_mode": "local", "opik_url": ""})
    assert opik_tracing.config()["mode"] == "local"
    # Absent (defensive: fake settings dicts in tests) -> local.
    monkeypatch.setattr(opik_tracing.settings, "get_settings",
                        lambda: {"opik_enabled": True})
    assert opik_tracing.config()["mode"] == "local"


def test_ui_status_shape(monkeypatch):
    """ui_status is the single home for the section's defaults (route is a passthrough)."""
    monkeypatch.setattr(opik_tracing, "has_api_key", lambda: True)
    monkeypatch.setattr(opik_tracing, "sdk_installed", lambda: False)
    monkeypatch.setattr(opik_tracing.settings, "get_settings",
                        lambda: {"opik_enabled": True, "opik_mode": "cloud",
                                 "opik_url": "", "opik_project": " ", "opik_workspace": "w"})
    st = opik_tracing.ui_status()
    assert st == {"enabled": True, "mode": "cloud", "url": "", "workspace": "w",
                  "project": "open-claude-desktop", "has_key": True,
                  "sdk_installed": False}


def test_bad_enum_values_clamp_on_read_and_write(tmp_path, monkeypatch):
    """settings.get/save clamp every enumerated setting — a corrupt opik_mode (or
    permission_mode etc.) can no longer persist or propagate."""
    import json as _json

    from ocd_core import config as _config
    from ocd_core import settings as _settings
    monkeypatch.setattr(_config, "SETTINGS_FILE", tmp_path / "settings.json")
    (tmp_path / "settings.json").write_text(_json.dumps(
        {"opik_mode": "banana", "permission_mode": "yolo", "theme": "neon",
         "code_execution": "everywhere", "search_provider": "bing"}), encoding="utf-8")
    s = _settings.get_settings()
    assert s["opik_mode"] == "local"
    assert s["permission_mode"] == "ask"
    assert s["theme"] == "light"
    assert s["code_execution"] == "auto"
    assert s["search_provider"] == "ddg"
    # save_settings refuses to persist a bad enum, clamping it to the default.
    out = _settings.save_settings({"opik_mode": "banana", "theme": "dark"})
    assert out["opik_mode"] == "local" and out["theme"] == "dark"
    on_disk = _json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert on_disk["opik_mode"] == "local"


def test_api_key_store_roundtrip(monkeypatch):
    """The key goes to the secret store (keychain), never settings; has_api_key tracks it."""
    from ocd_core import secrets
    store = secrets.MemoryStore()
    monkeypatch.setattr(secrets, "get_secret_store", lambda: store)
    monkeypatch.delenv("OPIK_API_KEY", raising=False)
    opik_tracing.reset_for_tests()

    assert opik_tracing.has_api_key() is False
    opik_tracing.set_api_key("  sk-secret  ")
    assert store.get("opik:api_key") == "sk-secret"      # trimmed, in the store
    assert opik_tracing.api_key() == "sk-secret"
    assert opik_tracing.has_api_key() is True
    opik_tracing.delete_api_key()
    assert opik_tracing.has_api_key() is False


def test_api_key_falls_back_to_env(monkeypatch):
    from ocd_core import secrets
    monkeypatch.setattr(secrets, "get_secret_store", lambda: secrets.MemoryStore())
    monkeypatch.setenv("OPIK_API_KEY", "env-key")
    opik_tracing.reset_for_tests()
    assert opik_tracing.api_key() == "env-key"


def test_observability_route_reports_status_without_the_key(monkeypatch, db):
    """GET /observability returns has_key (bool), never the key; PUT/DELETE manage it."""
    from ocd_core import secrets
    store = secrets.MemoryStore()
    monkeypatch.setattr(secrets, "get_secret_store", lambda: store)
    monkeypatch.delenv("OPIK_API_KEY", raising=False)
    opik_tracing.reset_for_tests()

    from app.main import app
    from fastapi.testclient import TestClient
    c = TestClient(app)

    st = c.get("/observability").json()
    assert st["has_key"] is False and "key" not in st
    assert st["mode"] in ("local", "cloud")

    r = c.put("/observability/key", json={"key": "sk-live"})
    assert r.json() == {"has_key": True}
    assert store.get("opik:api_key") == "sk-live"           # in keychain
    assert c.get("/observability").json()["has_key"] is True

    assert c.delete("/observability/key").json() == {"has_key": False}


def test_opik_settings_persist_through_the_route(monkeypatch, db, tmp_path):
    """Regression: opik_* fields must survive PUT /settings (they were dropped by an
    under-specified SettingsBody before this)."""
    from ocd_core import config

    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    from app.main import app
    from fastapi.testclient import TestClient
    c = TestClient(app)
    c.put("/settings", json={"opik_enabled": True, "opik_mode": "cloud",
                             "opik_project": "proj-x", "opik_workspace": "ws-y"})
    got = c.get("/settings").json()
    assert got["opik_enabled"] is True
    assert got["opik_mode"] == "cloud"
    assert got["opik_project"] == "proj-x"
    assert got["opik_workspace"] == "ws-y"


def test_scheduled_runs_are_traced(monkeypatch, fake_opik):
    """The scheduler was the one turn source invisible in Opik — its launcher must
    wrap run_turn in the tap with the 'scheduled' tag."""
    from ocd_core import scheduler

    _enable(monkeypatch)

    async def _fake_turn(*a, **k):
        yield {"type": "answer_open"}
        yield {"type": "delta", "scope": "answer", "text": "done"}

    monkeypatch.setattr(scheduler.agent, "run_turn", _fake_turn)
    captured = {}

    class _FakeTask:
        id = "t1"

    def _fake_start(goal, gen_factory):
        captured["gen"] = gen_factory()
        return _FakeTask()

    monkeypatch.setattr(scheduler.cowork.manager, "start", _fake_start)
    s = scheduler.Schedule(id="s1", goal="daily report", model="m")
    scheduler.default_launch(s)

    async def _drain():
        return [ev async for ev in captured["gen"]]

    out = asyncio.run(_drain())
    assert any(ev.get("type") == "delta" for ev in out)  # stream intact
    trace = _FakeOpik.instances[-1].traces[-1]
    assert "scheduled" in trace.kw["tags"]
    assert trace.ended["output"] == {"answer": "done"}
