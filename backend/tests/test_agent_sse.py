import json

import pytest
from fastapi.testclient import TestClient


async def _fake_run_turn(*args, **kwargs):
    yield {"type": "think_open", "phase": "plan"}
    yield {"type": "delta", "scope": "think", "text": "planning…"}
    yield {"type": "think_close", "elapsed": 0.1}
    yield {"type": "answer_open"}
    yield {"type": "delta", "scope": "answer", "text": "Hello"}
    yield {"type": "tool", "id": "t1", "name": "run_sql", "input": "SELECT 1"}
    yield {"type": "table", "id": "t1", "columns": ["n"], "rows": [{"n": 1}], "total": 1, "bytes": 10}


@pytest.fixture
def client(monkeypatch):
    from ocd_core import agent
    monkeypatch.setattr(agent, "run_turn", _fake_run_turn)
    from app.main import app
    return TestClient(app)


def _read_sse(resp):
    events, cur = [], {}
    for line in resp.text.splitlines():
        if line.startswith("event:"):
            cur["event"] = line[6:].strip()
        elif line.startswith("data:"):
            cur["data"] = json.loads(line[5:].strip())
        elif line == "" and cur:
            events.append(cur)
            cur = {}
    if cur:
        events.append(cur)
    return events


def test_agent_turn_streams_events(client, db):
    body = {"project_id": None, "goal": "hi", "history": [], "model": "glm-4-plus",
            "effort": "Low", "options": {}, "enabled_plugins": [],
            "enabled_connectors": [], "enabled_mcp": []}
    r = client.post("/agent/turn", json=body)
    assert r.status_code == 200
    evs = _read_sse(r)
    types = [e["event"] for e in evs]
    assert types[0] == "turn_start"
    assert types[1:5] == ["think_open", "delta", "think_close", "answer_open"]
    assert "table" in types and types[-1] == "done"
    delta = next(e for e in evs if e["event"] == "delta")
    assert delta["data"]["text"] in ("planning…", "Hello")


def test_agent_turn_rate_limited(monkeypatch, db):
    from ocd_core import agent, observability
    monkeypatch.setattr(agent, "run_turn", _fake_run_turn)
    monkeypatch.setattr(observability, "check_rate_limit", lambda user: False)  # always block
    from app.main import app
    c = TestClient(app)
    r = c.post("/agent/turn", json={"project_id": None, "goal": "hi", "history": [],
                                    "model": "m", "effort": "Low", "options": {},
                                    "enabled_plugins": [], "enabled_connectors": [], "enabled_mcp": []})
    assert r.status_code == 429


def test_agent_turn_unknown_workspace_id_detaches_instead_of_erroring(monkeypatch, db, tmp_path):
    """IMPORTANT fix: a stale/bogus workspace_id must not silently drop the caller's
    intent to attach a workspace -- it should surface a workspace_detached event AND
    run_turn must receive workspace_root=None (never a half-resolved state)."""
    from ocd_core import agent
    from ocd_core import workspace_registry as wr
    monkeypatch.setattr(wr, "_STORE", tmp_path / "workspaces.json")

    captured = {}

    async def _fake_run_turn_capture(*args, **kwargs):
        captured.update(kwargs)
        yield {"type": "answer_open"}
        yield {"type": "delta", "scope": "answer", "text": "ok"}

    monkeypatch.setattr(agent, "run_turn", _fake_run_turn_capture)
    from app.main import app
    c = TestClient(app)
    r = c.post("/agent/turn", json={"project_id": None, "goal": "hi", "history": [],
                                    "model": "m", "effort": "Low", "options": {},
                                    "enabled_plugins": [], "enabled_connectors": [],
                                    "enabled_mcp": [], "workspace_id": "does-not-exist"})
    assert r.status_code == 200
    evs = _read_sse(r)
    types = [e["event"] for e in evs]
    assert "workspace_detached" in types
    detached = next(e for e in evs if e["event"] == "workspace_detached")
    assert detached["data"]["workspace_id"] == "does-not-exist"
    assert captured.get("workspace_root") is None
