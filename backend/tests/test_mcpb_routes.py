"""REST plumbing for one-click extension install: multipart upload -> inspect /
install, user_config passthrough, and McpbError -> HTTP 400 mapping."""
import io
import json
import zipfile

import pytest
from app.main import app
from fastapi.testclient import TestClient
from ocd_core import integrations

client = TestClient(app)

_SERVER_PY = """\
import os
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mcpb-route-fixture")


@mcp.tool()
def whoami() -> str:
    "Return the greeting configured at install time."
    return os.environ.get("GREETING", "unset")


if __name__ == "__main__":
    mcp.run()
"""


def _bundle_bytes() -> bytes:
    manifest = {
        "manifest_version": "0.1",
        "name": "Route Ext",
        "version": "0.9.0",
        "description": "route test bundle",
        "server": {
            "type": "python",
            "mcp_config": {
                "command": "python",
                "args": ["${__dirname}/server/main.py"],
                "env": {"GREETING": "${user_config.greeting}"},
            },
        },
        "user_config": {"greeting": {"type": "string", "required": True}},
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("server/main.py", _SERVER_PY)
    return buf.getvalue()


@pytest.fixture
def isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(integrations, "EXTENSIONS_DIR", tmp_path / "extensions")
    monkeypatch.setattr(integrations, "MCP_FILE", tmp_path / "mcp_servers.json")
    yield
    for s in integrations._load_mcp_servers():
        try:
            integrations.mcp_registry.registry.drop(integrations._resolve_cfg(s))
        except Exception:
            pass


def test_add_oauth_server_route(isolate):
    r = client.post("/mcp-servers/oauth",
                    json={"name": "Remote OAuth", "url": "https://mcp.example.com/mcp"})
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["auth_mode"] == "oauth" and item["status"] == "unauthorized"
    # It appears in the listing as an unauthorized oauth connector.
    listed = {s["id"]: s for s in client.get("/mcp-servers").json()}
    assert listed[item["id"]]["auth_mode"] == "oauth"
    assert listed[item["id"]]["authorized"] is False


def test_authorize_unknown_server_is_400(isolate):
    r = client.post("/mcp-servers/nope/authorize")
    assert r.status_code == 400
    assert "OAuth" in r.json()["detail"]


def test_inspect_reads_manifest(isolate):
    r = client.post("/mcp-servers/inspect",
                    files={"file": ("route.mcpb", _bundle_bytes(), "application/zip")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Route Ext"
    assert body["version"] == "0.9.0"
    assert "greeting" in body["user_config"]


def test_install_registers_server(isolate):
    r = client.post(
        "/mcp-servers/install",
        files={"file": ("route.mcpb", _bundle_bytes(), "application/zip")},
        data={"user_config": json.dumps({"greeting": "hey"})},
    )
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["source"] == "mcpb"
    assert item["env"]["GREETING"] == "hey"
    # And it shows up in the listing endpoint.
    listed = client.get("/mcp-servers").json()
    assert any(s["id"] == item["id"] for s in listed)


def test_install_missing_required_user_config_is_400(isolate):
    r = client.post(
        "/mcp-servers/install",
        files={"file": ("route.mcpb", _bundle_bytes(), "application/zip")},
        data={"user_config": "{}"},
    )
    assert r.status_code == 400
    assert "greeting" in r.json()["detail"]


def test_install_bad_user_config_json_is_400(isolate):
    r = client.post(
        "/mcp-servers/install",
        files={"file": ("route.mcpb", _bundle_bytes(), "application/zip")},
        data={"user_config": "not json"},
    )
    assert r.status_code == 400


def test_install_bad_zip_is_400(isolate):
    r = client.post(
        "/mcp-servers/install",
        files={"file": ("bad.mcpb", b"not a zip", "application/zip")},
        data={"user_config": "{}"},
    )
    assert r.status_code == 400
    assert "zip" in r.json()["detail"].lower()
