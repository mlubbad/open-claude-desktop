"""Extension auto-update (P1-13): version ordering, GitHub repo parsing, the
release check, one-click reinstall with keychain-stored user_config, and the
bundled-Node fallback for stdio commands."""
import io
import json
import zipfile

import pytest
from ocd_core import integrations, secrets
from ocd_core.integrations import McpbError


def _manifest(version="1.0.0", *, required=("greeting",), repository=True) -> dict:
    m = {
        "manifest_version": "0.1",
        "name": "Fixture Ext",
        "version": version,
        "description": "update fixture",
        "server": {
            "type": "python",
            "entry_point": "server/main.py",
            "mcp_config": {
                "command": "python",
                "args": ["${__dirname}/server/main.py"],
                "env": {k.upper(): "${user_config." + k + "}" for k in required},
            },
        },
        "user_config": {k: {"type": "string", "required": True} for k in required},
    }
    if repository:
        m["repository"] = {"type": "git", "url": "https://github.com/acme/fixture-ext.git"}
    return m


def _bundle_bytes(manifest: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("server/main.py", "print('hi')\n")
    return buf.getvalue()


class FakeResp:
    def __init__(self, status_code=200, json_data=None, content=b""):
        self.status_code = status_code
        self._json = json_data or {}
        self.content = content

    def json(self):
        return self._json


def _release(tag: str, asset_name="ext.mcpb", body="notes") -> dict:
    return {"tag_name": tag, "body": body,
            "assets": [{"name": asset_name,
                        "browser_download_url": f"https://example.com/{asset_name}"}]}


@pytest.fixture
def isolate(monkeypatch, tmp_path):
    """Scratch EXTENSIONS_DIR + mcp_servers.json, and a fake add_mcp_server that
    registers without spawning a real stdio subprocess (discovery isn't under test
    here — test_mcpb.py covers the real end-to-end install)."""
    monkeypatch.setattr(integrations, "EXTENSIONS_DIR", tmp_path / "extensions")
    monkeypatch.setattr(integrations, "MCP_FILE", tmp_path / "mcp_servers.json")

    def fake_add(name, command="", args=None, *, url="", transport="", env=None,
                 headers=None, auth_token=""):
        sid = integrations._slug(name)
        items = [s for s in integrations._load_mcp_servers() if s["id"] != sid]
        item = {"id": sid, "name": name, "transport": "stdio", "command": command,
                "args": args or [], "env": env or {}, "tools": [],
                "status": "connected", "detail": ""}
        items.append(item)
        integrations._save_mcp_servers(items)
        return item

    monkeypatch.setattr(integrations, "add_mcp_server", fake_add)
    return tmp_path


def _install(tmp_path, manifest, values):
    p = tmp_path / "ext.mcpb"
    p.write_bytes(_bundle_bytes(manifest))
    return integrations.install_mcpb(p, values)


def test_ver_key_orders_numeric_runs():
    vk = integrations._ver_key
    assert vk("v1.2.10") > vk("1.2.9")
    assert vk("2.0") > vk("1.9.9")
    assert vk("1.2.3") == vk("v1.2.3")
    assert vk("") < vk("0.0.1")


def test_gh_repo_of_parses_common_shapes():
    of = integrations._gh_repo_of
    assert of("https://github.com/acme/fixture-ext.git") == ("acme", "fixture-ext")
    assert of("https://github.com/acme/fixture-ext/") == ("acme", "fixture-ext")
    assert of("git@github.com:acme/fixture-ext.git") == ("acme", "fixture-ext")
    assert of("https://gitlab.com/acme/x") is None
    assert of("") is None


def test_install_records_repository_and_keychain_user_config(isolate):
    item = _install(isolate, _manifest(), {"greeting": "hi"})
    assert item["repository"] == "https://github.com/acme/fixture-ext.git"
    raw = secrets.get_secret_store().get(f"mcp:{item['id']}:user_config")
    assert json.loads(raw) == {"greeting": "hi"}


def test_uninstall_deletes_keychain_user_config(isolate):
    item = _install(isolate, _manifest(), {"greeting": "hi"})
    integrations.remove_mcp_server(item["id"])
    assert secrets.get_secret_store().get(f"mcp:{item['id']}:user_config") is None


def test_check_update_reports_newer_release(isolate, monkeypatch):
    item = _install(isolate, _manifest("1.0.0"), {"greeting": "hi"})
    monkeypatch.setattr(integrations, "_http_get",
                        lambda url, headers, timeout=15: FakeResp(200, _release("v1.2.0")))
    info = integrations.check_mcpb_update(item["id"])
    assert info["current"] == "1.0.0"
    assert info["latest"] == "1.2.0"
    assert info["url"].endswith("ext.mcpb")
    assert info["notes"] == "notes"


def test_check_update_when_current_returns_no_latest(isolate, monkeypatch):
    item = _install(isolate, _manifest("1.2.0"), {"greeting": "hi"})
    monkeypatch.setattr(integrations, "_http_get",
                        lambda url, headers, timeout=15: FakeResp(200, _release("v1.2.0")))
    info = integrations.check_mcpb_update(item["id"])
    assert info["latest"] is None


def test_check_update_without_repository_is_actionable(isolate):
    item = _install(isolate, _manifest(repository=False), {"greeting": "hi"})
    with pytest.raises(McpbError, match="no GitHub repository"):
        integrations.check_mcpb_update(item["id"])


def test_check_update_rejects_non_extension(isolate):
    with pytest.raises(McpbError, match="not an installed extension"):
        integrations.check_mcpb_update("nope")


def test_update_reinstalls_with_stored_user_config(isolate, monkeypatch):
    item = _install(isolate, _manifest("1.0.0"), {"greeting": "hi"})
    new_bundle = _bundle_bytes(_manifest("2.0.0"))

    def fake_get(url, headers, timeout=15):
        if "api.github.com" in url:
            return FakeResp(200, _release("v2.0.0"))
        return FakeResp(200, content=new_bundle)

    monkeypatch.setattr(integrations, "_http_get", fake_get)
    updated = integrations.update_mcpb(item["id"])
    # Reinstalled in place: same id, new version, and the keychain-stored greeting
    # answered the new manifest's required user_config without re-prompting.
    assert updated["id"] == item["id"]
    assert updated["version"] == "2.0.0"
    assert updated["env"]["GREETING"] == "hi"


def test_update_surfaces_new_required_fields(isolate, monkeypatch):
    item = _install(isolate, _manifest("1.0.0"), {"greeting": "hi"})
    new_bundle = _bundle_bytes(_manifest("2.0.0", required=("greeting", "token")))

    def fake_get(url, headers, timeout=15):
        if "api.github.com" in url:
            return FakeResp(200, _release("v2.0.0"))
        return FakeResp(200, content=new_bundle)

    monkeypatch.setattr(integrations, "_http_get", fake_get)
    with pytest.raises(McpbError, match="required user_config: token"):
        integrations.update_mcpb(item["id"])
    # Fail-fast: the installed record is untouched…
    assert integrations._find_mcp(item["id"])["version"] == "1.0.0"
    # …and providing the missing value completes the update.
    updated = integrations.update_mcpb(item["id"], {"token": "t0k"})
    assert updated["version"] == "2.0.0"
    assert updated["env"] == {"GREETING": "hi", "TOKEN": "t0k"}


def test_update_when_already_current_raises(isolate, monkeypatch):
    item = _install(isolate, _manifest("2.0.0"), {"greeting": "hi"})
    monkeypatch.setattr(integrations, "_http_get",
                        lambda url, headers, timeout=15: FakeResp(200, _release("v2.0.0")))
    with pytest.raises(McpbError, match="already up to date"):
        integrations.update_mcpb(item["id"])


def test_resolve_cfg_falls_back_to_bundled_node(monkeypatch, tmp_path):
    node = tmp_path / "node"
    node.write_text("#!/bin/sh\n")
    monkeypatch.setenv("OCD_NODE", str(node))
    monkeypatch.setattr(integrations.shutil, "which", lambda cmd: None)
    out = integrations._resolve_cfg({"id": "x", "command": "node", "args": ["srv.js"]})
    assert out["command"] == str(node)
    # The bundled runtime's dir leads PATH so child spawns resolve the same node.
    assert out["env"]["PATH"].startswith(str(tmp_path))


def test_resolve_cfg_missing_command_without_bundle_stays_actionable(monkeypatch):
    monkeypatch.delenv("OCD_NODE", raising=False)
    monkeypatch.setattr(integrations.shutil, "which", lambda cmd: None)
    with pytest.raises(FileNotFoundError, match="not found on this machine"):
        integrations._resolve_cfg({"id": "x", "command": "node", "args": []})
