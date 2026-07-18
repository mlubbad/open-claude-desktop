"""POST /mcp-servers spawns an arbitrary local command at discovery. It must be
refused when the backend is unauthenticated (RCE for anyone who can reach the
port), unless the operator explicitly opts in via OCD_ALLOW_UNAUTHENTICATED.
current_user is overridden so the tests don't depend on ambient auth config.
"""
from app.deps import current_user
from app.routes import integrations as ig_route
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ocd_core import auth, integrations, netguard


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(ig_route.router)
    app.dependency_overrides[current_user] = lambda: "tester"
    return TestClient(app)


def test_add_mcp_refused_when_unauthenticated(monkeypatch):
    monkeypatch.setattr(auth, "auth_enabled", lambda: False)
    monkeypatch.setattr(netguard, "allow_unauthenticated", lambda env=None: False)
    calls = {"n": 0}
    monkeypatch.setattr(integrations, "add_mcp_server",
                        lambda *a, **k: calls.__setitem__("n", calls["n"] + 1) or {"id": "x"})
    r = _client().post("/mcp-servers", json={"name": "x", "command": "calc.exe", "args": []})
    assert r.status_code == 403
    assert calls["n"] == 0  # the command must never be spawned


def test_add_mcp_allowed_when_auth_enabled(monkeypatch):
    monkeypatch.setattr(auth, "auth_enabled", lambda: True)
    monkeypatch.setattr(integrations, "add_mcp_server",
                        lambda name, command, args=None: {"id": "x", "status": "connected"})
    r = _client().post("/mcp-servers", json={"name": "x", "command": "echo", "args": ["hi"]})
    assert r.status_code == 200
    assert r.json()["status"] == "connected"


def test_add_mcp_allowed_with_explicit_optout(monkeypatch):
    monkeypatch.setattr(auth, "auth_enabled", lambda: False)
    monkeypatch.setattr(netguard, "allow_unauthenticated", lambda env=None: True)
    monkeypatch.setattr(integrations, "add_mcp_server",
                        lambda *a, **k: {"id": "x", "status": "connected"})
    r = _client().post("/mcp-servers", json={"name": "x", "command": "echo", "args": []})
    assert r.status_code == 200
