"""Actionable stdio-connector failures (the reported playwright/markitdown cases):
a missing CLI fails with a message naming the command (not a raw '[WinError 2] The
system cannot find the file specified'), a cold-start timeout points at Retry, and
the Retry route re-connects from scratch.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from ocd_core import config, integrations, mcp_registry


@pytest.fixture
def mcp_file(tmp_path, monkeypatch):
    monkeypatch.setattr(integrations, "MCP_FILE", tmp_path / "mcp.json")
    monkeypatch.setattr(config, "STDIO_MCP_ENABLED", True)
    return tmp_path / "mcp.json"


def test_missing_command_yields_actionable_error(mcp_file, monkeypatch):
    """docker not installed / not on the backend's PATH -> the card must NAME the
    missing command and say what to do, before any spawn is attempted."""
    monkeypatch.setattr(integrations.shutil, "which", lambda c: None)
    res = integrations.add_mcp_server("markitdown", command="docker",
                                      args=["run", "--rm", "-i", "markitdown-mcp:latest"])
    assert res["status"] == "error"
    assert "'docker' was not found" in res["detail"]
    assert "Retry" in res["detail"]  # tells the user the recovery path


def test_present_command_passes_preflight(mcp_file, monkeypatch):
    monkeypatch.setattr(integrations.shutil, "which", lambda c: "/usr/bin/" + c)
    seen = {}

    def fake_discover(cfg, timeout=None):
        seen["command"] = cfg["command"]
        return [{"name": "t", "description": "", "inputSchema": {}}]

    monkeypatch.setattr(mcp_registry.registry, "discover", fake_discover)
    res = integrations.add_mcp_server("ok", command="npx", args=["@playwright/mcp@latest"])
    assert res["status"] == "connected"
    assert seen["command"] == "npx"  # preflight checks but never rewrites the command


def test_cold_start_timeout_message_points_at_retry(mcp_file, monkeypatch):
    monkeypatch.setattr(integrations.shutil, "which", lambda c: "/usr/bin/" + c)

    def slow_discover(cfg, timeout=None):
        raise TimeoutError()

    monkeypatch.setattr(mcp_registry.registry, "discover", slow_discover)
    res = integrations.add_mcp_server("playwright", command="npx", args=["@playwright/mcp@latest"])
    assert res["status"] == "error"
    assert "Retry" in res["detail"]
    assert "download" in res["detail"]  # explains WHY a first run can time out


def test_refresh_reconnects_from_scratch(mcp_file, monkeypatch):
    """The Retry path: an errored server re-discovers (fresh spawn) and recovers."""
    monkeypatch.setattr(integrations.shutil, "which", lambda c: "/usr/bin/" + c)
    calls = {"drop": 0, "n": 0}

    def flaky_discover(cfg, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError()  # cold start: the npx download outlives the window
        return [{"name": "browse", "description": "", "inputSchema": {}}]

    monkeypatch.setattr(mcp_registry.registry, "discover", flaky_discover)
    monkeypatch.setattr(mcp_registry.registry, "drop",
                        lambda cfg: calls.__setitem__("drop", calls["drop"] + 1))

    added = integrations.add_mcp_server("playwright", command="npx", args=["@playwright/mcp@latest"])
    assert added["status"] == "error"

    refreshed = integrations.refresh_mcp_server(added["id"])
    assert calls["drop"] == 1  # killed the old session -> genuinely fresh spawn
    assert refreshed["status"] == "connected"
    assert refreshed["detail"] == "1 tools"
    # ...and the recovery is persisted.
    saved = next(s for s in integrations.list_mcp_servers() if s["id"] == added["id"])
    assert saved["status"] == "connected"


def test_refresh_route(mcp_file, monkeypatch, db):
    from app.main import app
    client = TestClient(app)
    assert client.post("/mcp-servers/nope/refresh").status_code == 404

    monkeypatch.setattr(integrations.shutil, "which", lambda c: "/usr/bin/" + c)
    monkeypatch.setattr(mcp_registry.registry, "discover",
                        lambda cfg, timeout=None: [{"name": "t", "description": "", "inputSchema": {}}])
    monkeypatch.setattr(mcp_registry.registry, "drop", lambda cfg: None)
    added = integrations.add_mcp_server("ok", command="npx", args=[])
    r = client.post(f"/mcp-servers/{added['id']}/refresh")
    assert r.status_code == 200 and r.json()["status"] == "connected"


def test_spawn_failure_surfaces_server_stderr(tmp_path):
    """A server that dies on startup shows ITS OWN error output on the card —
    exercised through the real registry + a real subprocess."""
    import sys
    cfg = {"id": "dies", "transport": "stdio", "command": sys.executable,
           "args": ["-c", "import sys; sys.stderr.write('boom: could not reach daemon'); sys.exit(7)"],
           "env": {}}
    with pytest.raises(Exception) as ei:
        mcp_registry.registry.discover(cfg, timeout=15)
    assert "boom: could not reach daemon" in str(ei.value)


def test_add_timeout_default_covers_cold_starts():
    """Guard the regression that shipped 25s: first-run npx/docker downloads need
    more headroom than that (the reported playwright failure)."""
    assert config.MCP_ADD_TIMEOUT_SEC >= 60
