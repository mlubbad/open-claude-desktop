"""Desktop extension bundle (.mcpb / legacy .dxt) install: manifest parsing,
user_config validation, zip-slip safety, placeholder substitution, and a real
end-to-end install that unpacks a bundled stdio MCP server and discovers its tool.
"""
import io
import json
import zipfile

import pytest
from ocd_core import integrations
from ocd_core.integrations import McpbError

# A minimal but real stdio MCP server, bundled inside the fixture .mcpb. It reads
# an env var (proving user_config -> env substitution) and exposes one tool.
_SERVER_PY = """\
import os
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mcpb-fixture")


@mcp.tool()
def whoami() -> str:
    "Return the greeting configured at install time."
    return os.environ.get("GREETING", "unset")


if __name__ == "__main__":
    mcp.run()
"""


def _manifest(**over) -> dict:
    m = {
        "manifest_version": "0.1",
        "name": "Fixture Ext",
        "version": "1.2.3",
        "description": "A tiny bundled MCP server for tests.",
        "server": {
            "type": "python",
            "entry_point": "server/main.py",
            "mcp_config": {
                "command": "python",
                "args": ["${__dirname}/server/main.py"],
                "env": {"GREETING": "${user_config.greeting}"},
            },
        },
        "user_config": {
            "greeting": {"type": "string", "title": "Greeting", "required": True},
        },
    }
    m.update(over)
    return m


def _make_bundle(tmp_path, manifest, *, server=_SERVER_PY, extra=None, name="ext.mcpb"):
    """Write a .mcpb zip to tmp_path and return its path. `extra` is a dict of
    {arcname: bytes|str} for injecting adversarial entries (e.g. zip-slip)."""
    p = tmp_path / name
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        if server is not None:
            zf.writestr("server/main.py", server)
        for arc, data in (extra or {}).items():
            zf.writestr(arc, data)
    p.write_bytes(buf.getvalue())
    return p


@pytest.fixture
def isolate(monkeypatch, tmp_path):
    """Point EXTENSIONS_DIR + mcp_servers.json at a scratch dir so tests never
    touch the repo tree or a developer's real connectors."""
    monkeypatch.setattr(integrations, "EXTENSIONS_DIR", tmp_path / "extensions")
    monkeypatch.setattr(integrations, "MCP_FILE", tmp_path / "mcp_servers.json")
    yield tmp_path
    # Tear down any spawned MCP sessions so subprocesses don't leak between tests.
    for s in integrations._load_mcp_servers():
        try:
            integrations.mcp_registry.registry.drop(integrations._resolve_cfg(s))
        except Exception:
            pass


def test_manifest_info_reads_without_installing(isolate, tmp_path):
    p = _make_bundle(tmp_path, _manifest())
    info = integrations.mcpb_manifest_info(p)
    assert info["name"] == "Fixture Ext"
    assert info["version"] == "1.2.3"
    assert "greeting" in info["user_config"]
    # nothing was unpacked / registered
    assert not (tmp_path / "extensions").exists()
    assert integrations.list_mcp_servers() == []


def test_missing_required_user_config_is_rejected(isolate, tmp_path):
    p = _make_bundle(tmp_path, _manifest())
    with pytest.raises(McpbError, match="required user_config: greeting"):
        integrations.install_mcpb(p)  # no greeting provided
    # fail-fast: nothing unpacked
    assert not (tmp_path / "extensions" / "fixture_ext").exists()


def test_zip_slip_entry_is_rejected(isolate, tmp_path):
    p = _make_bundle(tmp_path, _manifest(), extra={"../evil.txt": "pwned"})
    with pytest.raises(McpbError, match="unsafe path"):
        integrations.install_mcpb(p, {"greeting": "hi"})
    # the traversal target must not exist
    assert not (tmp_path / "evil.txt").exists()


def test_bad_zip_is_rejected(isolate, tmp_path):
    p = tmp_path / "not.mcpb"
    p.write_bytes(b"this is not a zip file")
    with pytest.raises(McpbError, match="bad zip"):
        integrations.install_mcpb(p, {"greeting": "hi"})


def test_manifest_without_server_is_rejected(isolate, tmp_path):
    m = _manifest()
    del m["server"]
    p = _make_bundle(tmp_path, m)
    with pytest.raises(McpbError, match="server"):
        integrations.install_mcpb(p, {"greeting": "hi"})


def test_install_end_to_end_registers_and_discovers_tool(isolate, tmp_path):
    p = _make_bundle(tmp_path, _manifest())
    item = integrations.install_mcpb(p, {"greeting": "hello-world"})

    # Registered as an mcpb-sourced stdio server, unpacked under EXTENSIONS_DIR.
    assert item["source"] == "mcpb"
    assert item["version"] == "1.2.3"
    assert item["transport"] == "stdio"
    assert item["command"] == "${PYTHON}"  # python -> bundled interpreter
    assert item["env"]["GREETING"] == "hello-world"  # user_config substituted
    unpacked = tmp_path / "extensions" / "fixture_ext" / "server" / "main.py"
    assert unpacked.is_file()

    # It really connected and exposed its tool (real stdio subprocess).
    assert item["status"] == "connected", item.get("detail")
    tool_names = [t["name"] for t in item.get("tools", [])]
    assert "whoami" in tool_names

    # Visible through the public listing with its source tag.
    listed = integrations.list_mcp_servers()
    assert any(s["id"] == item["id"] and s["source"] == "mcpb" for s in listed)


def test_uninstall_reclaims_unpacked_files(isolate, tmp_path):
    p = _make_bundle(tmp_path, _manifest())
    item = integrations.install_mcpb(p, {"greeting": "hi"})
    ext_dir = tmp_path / "extensions" / "fixture_ext"
    assert ext_dir.is_dir()

    integrations.remove_mcp_server(item["id"])
    assert not ext_dir.exists()  # files reclaimed
    assert integrations.list_mcp_servers() == []


def test_default_user_config_value_is_used(isolate, tmp_path):
    m = _manifest()
    m["user_config"]["greeting"] = {"type": "string", "default": "from-default"}
    p = _make_bundle(tmp_path, m)
    item = integrations.install_mcpb(p)  # no value provided -> falls back to default
    assert item["env"]["GREETING"] == "from-default"
