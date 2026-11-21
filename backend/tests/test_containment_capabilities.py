"""Days 1-3 containment: executable/autonomous capabilities default off."""
from __future__ import annotations

import importlib

import pytest


def test_fresh_install_capability_defaults_are_fail_closed(monkeypatch):
    for key in (
        "MARKETPLACE_ALLOW_REMOTE",
        "OCD_ENABLE_STDIO_MCP",
        "OCD_ALLOW_HOST_EXEC",
        "CODE_EXECUTION_MODE",
        "PERMISSION_MODE",
        "SCHEDULER_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)

    from ocd_core import config

    cfg = importlib.reload(config)
    assert cfg.MARKETPLACE_ALLOW_REMOTE is False
    assert cfg.STDIO_MCP_ENABLED is True   # local-first: stdio MCP on by default (loopback + gated approval)
    assert cfg.HOST_EXECUTION_ENABLED is False
    assert cfg.SCHEDULER_ENABLED is False
    assert cfg.DEFAULT_SETTINGS["code_execution"] == "docker"
    assert cfg.DEFAULT_SETTINGS["permission_mode"] == "ask"
    assert cfg.PERMISSION_MODE == "ask"


def test_remote_marketplace_requires_explicit_opt_in(monkeypatch):
    from ocd_core import config, marketplace

    monkeypatch.setattr(config, "MARKETPLACE_ALLOW_REMOTE", False)
    assert marketplace.remote_allowed() is False
    monkeypatch.setattr(config, "MARKETPLACE_ALLOW_REMOTE", True)
    assert marketplace.remote_allowed() is True


def test_stdio_mcp_registration_is_blocked_before_spawn(monkeypatch, tmp_path):
    from ocd_core import config, integrations, mcp_registry

    monkeypatch.setattr(config, "STDIO_MCP_ENABLED", False)
    monkeypatch.setattr(integrations, "MCP_FILE", tmp_path / "mcp.json")
    monkeypatch.setattr(
        mcp_registry.registry,
        "discover",
        lambda *_a, **_kw: pytest.fail("disabled stdio MCP must not spawn"),
    )

    with pytest.raises(integrations.McpbError, match="disabled"):
        integrations.add_mcp_server("local-command", command="python", args=["server.py"])
    assert not integrations.MCP_FILE.exists()


def test_stdio_mcp_can_be_enabled_explicitly(monkeypatch, tmp_path):
    from ocd_core import config, integrations, mcp_registry

    monkeypatch.setattr(config, "STDIO_MCP_ENABLED", True)
    monkeypatch.setattr(integrations, "MCP_FILE", tmp_path / "mcp.json")
    monkeypatch.setattr(integrations.shutil, "which", lambda command: f"/bin/{command}")
    monkeypatch.setattr(mcp_registry.registry, "discover", lambda *_a, **_kw: [])

    result = integrations.add_mcp_server("explicit", command="python", args=["server.py"])
    assert result["status"] == "connected"


def test_existing_stdio_mcp_cannot_execute_while_disabled(monkeypatch):
    from ocd_core import config, integrations

    server = {
        "id": "local",
        "name": "Local",
        "transport": "stdio",
        "command": "python",
        "tools": [{"name": "run", "inputSchema": {}}],
    }
    monkeypatch.setattr(config, "STDIO_MCP_ENABLED", False)
    monkeypatch.setattr(integrations, "_load_mcp_servers", lambda: [server])
    monkeypatch.setattr(
        integrations.mcp_registry.registry,
        "call",
        lambda *_a, **_kw: pytest.fail("disabled stdio MCP must not execute"),
    )

    assert integrations.mcp_tools(["local"]) == []
    assert "disabled" in integrations.call_mcp("mcp_local_run", {}).lower()


def test_host_execution_requires_explicit_opt_in(monkeypatch, tmp_path):
    from ocd_core import config, integrations

    monkeypatch.setattr(config, "HOST_EXECUTION_ENABLED", False)
    monkeypatch.setattr(integrations, "SANDBOX_ROOT", tmp_path / "sandbox")
    monkeypatch.setattr(integrations, "_code_execution_mode", lambda: "local")
    monkeypatch.setattr(
        integrations,
        "_run_local",
        lambda *_a, **_kw: pytest.fail("host execution must not run"),
    )

    result = integrations.execute_code("print('unsafe')", "general")
    assert result["ok"] is False
    assert result["engine"] == "host-disabled"
    assert "OCD_ALLOW_HOST_EXEC" in result["stderr"]


def test_cowork_defaults_to_manual_approval():
    from app.routes.cowork import CoworkStart

    base = {"goal": "review this", "model": "test-model"}
    assert CoworkStart(**base).approval == "manual"
    assert CoworkStart(**base, approval="").approval == "manual"
    assert CoworkStart(**base, approval="skip").approval == "skip"


def test_stdio_mcp_route_returns_forbidden_when_disabled(monkeypatch, tmp_path):
    from app.main import app
    from fastapi.testclient import TestClient
    from ocd_core import config, integrations

    monkeypatch.setattr(config, "STDIO_MCP_ENABLED", False)
    monkeypatch.setattr(integrations, "MCP_FILE", tmp_path / "mcp.json")
    response = TestClient(app, raise_server_exceptions=False).post(
        "/mcp-servers", json={"name": "local", "command": "python", "args": []}
    )
    assert response.status_code == 403
    assert "disabled" in response.json()["detail"]
