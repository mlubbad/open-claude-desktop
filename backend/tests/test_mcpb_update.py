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


def _bundle_bytes(manifest: dict, *, extra: dict | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("server/main.py", "print('hi')\n")
        for arc, data in (extra or {}).items():
            zf.writestr(arc, data)
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
    monkeypatch.setattr(integrations.config, "STDIO_MCP_ENABLED", True)

    def fake_add(name, command="", args=None, *, url="", transport="", env=None,
                 headers=None, auth_token=""):
        sid = integrations._slug(name)
        items = [s for s in integrations._load_mcp_servers() if s["id"] != sid]
        item = {"id": sid, "name": name, "transport": "stdio", "command": command,
                "args": args or [], "env": env or {}, "tools": list(fake_add.tools),
                "status": "connected", "detail": ""}
        items.append(item)
        integrations._save_mcp_servers(items)
        return item

    # Tests that exercise disabled_tools set this to simulate what discovery found.
    fake_add.tools = []
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


def test_update_preserves_disabled_tools(isolate, monkeypatch):
    """A one-click update must not silently re-enable tools the user switched off
    (the P1-12 disable doubles as the dispatch-time allowlist)."""
    integrations.add_mcp_server.tools = [{"name": "read_file"}, {"name": "delete_file"}]
    item = _install(isolate, _manifest("1.0.0"), {"greeting": "hi"})
    integrations.set_mcp_tool_enabled(item["id"], "delete_file", False)
    integrations.set_mcp_tool_enabled(item["id"], "gone_tool", False)  # won't survive

    new_bundle = _bundle_bytes(_manifest("2.0.0"))

    def fake_get(url, headers, timeout=15):
        if "api.github.com" in url:
            return FakeResp(200, _release("v2.0.0"))
        return FakeResp(200, content=new_bundle)

    monkeypatch.setattr(integrations, "_http_get", fake_get)
    updated = integrations.update_mcpb(item["id"])
    # Kept — and pruned to tools that still exist in the new version.
    assert updated["disabled_tools"] == ["delete_file"]


def test_update_keeps_disabled_tools_when_discovery_fails(isolate, monkeypatch):
    integrations.add_mcp_server.tools = [{"name": "delete_file"}]
    item = _install(isolate, _manifest("1.0.0"), {"greeting": "hi"})
    integrations.set_mcp_tool_enabled(item["id"], "delete_file", False)
    integrations.add_mcp_server.tools = []  # the update's discovery finds nothing

    def fake_get(url, headers, timeout=15):
        if "api.github.com" in url:
            return FakeResp(200, _release("v2.0.0"))
        return FakeResp(200, content=_bundle_bytes(_manifest("2.0.0")))

    monkeypatch.setattr(integrations, "_http_get", fake_get)
    updated = integrations.update_mcpb(item["id"])
    # No tool list to prune against — keep the user's choices, don't forget them.
    assert updated["disabled_tools"] == ["delete_file"]


def test_bad_update_bundle_leaves_working_install_intact(isolate, monkeypatch):
    """A hostile/corrupt downloaded bundle must never destroy the current install:
    extraction happens in a staging dir and swaps in only on success."""
    item = _install(isolate, _manifest("1.0.0"), {"greeting": "hi"})
    installed = isolate / "extensions" / "fixture_ext" / "server" / "main.py"
    assert installed.is_file()

    evil = _bundle_bytes(_manifest("2.0.0"), extra={"../evil.py": "pwned"})

    def fake_get(url, headers, timeout=15):
        if "api.github.com" in url:
            return FakeResp(200, _release("v2.0.0"))
        return FakeResp(200, content=evil)

    monkeypatch.setattr(integrations, "_http_get", fake_get)
    with pytest.raises(McpbError, match="unsafe path"):
        integrations.update_mcpb(item["id"])
    # The v1 files and record are untouched; no staging debris left behind.
    assert installed.is_file()
    assert integrations._find_mcp(item["id"])["version"] == "1.0.0"
    assert not (isolate / "extensions" / "fixture_ext.staging").exists()


def test_check_update_network_error_is_actionable(isolate, monkeypatch):
    """Offline must surface as a clean McpbError (the route maps it to a 400),
    not a 500 with a traceback."""
    item = _install(isolate, _manifest(), {"greeting": "hi"})

    def boom(url, headers, timeout=15):
        raise OSError("connection refused")

    monkeypatch.setattr(integrations, "_http_get", boom)
    with pytest.raises(McpbError, match="unreachable"):
        integrations.check_mcpb_update(item["id"])


def test_update_that_renames_extension_retires_the_old_record(isolate, monkeypatch):
    item = _install(isolate, _manifest("1.0.0"), {"greeting": "hi"})
    renamed = _manifest("2.0.0")
    renamed["name"] = "Fixture Ext Renamed"

    def fake_get(url, headers, timeout=15):
        if "api.github.com" in url:
            return FakeResp(200, _release("v2.0.0"))
        return FakeResp(200, content=_bundle_bytes(renamed))

    monkeypatch.setattr(integrations, "_http_get", fake_get)
    updated = integrations.update_mcpb(item["id"])
    assert updated["id"] == "fixture_ext_renamed"
    # The old record, its unpacked files, and its keychain entry are all gone;
    # the stored user_config answers moved with the new id.
    ids = [s["id"] for s in integrations._load_mcp_servers()]
    assert ids == ["fixture_ext_renamed"]
    assert not (isolate / "extensions" / "fixture_ext").exists()
    store = secrets.get_secret_store()
    assert store.get("mcp:fixture_ext:user_config") is None
    assert json.loads(store.get("mcp:fixture_ext_renamed:user_config")) == {"greeting": "hi"}


def test_release_tag_identity_breaks_update_loops(isolate, monkeypatch):
    """A repo whose tag carries more numeric runs than its manifest version (tag
    v1.2.0, manifest "1.2") must not offer the same update forever."""
    item = _install(isolate, _manifest("1.2"), {"greeting": "hi"})

    def fake_get(url, headers, timeout=15):
        if "api.github.com" in url:
            return FakeResp(200, _release("v1.2.0"))
        return FakeResp(200, content=_bundle_bytes(_manifest("1.2")))

    monkeypatch.setattr(integrations, "_http_get", fake_get)
    assert integrations.check_mcpb_update(item["id"])["latest"] == "1.2.0"
    integrations.update_mcpb(item["id"])  # installs the same manifest version
    # The installed release tag is remembered, so the loop ends here.
    assert integrations.check_mcpb_update(item["id"])["latest"] is None


def test_non_github_homepage_is_not_recorded_as_repository(isolate):
    m = _manifest(repository=False)
    m["homepage"] = "https://example.com/tool"
    item = _install(isolate, m, {"greeting": "hi"})
    # An uncheckable URL would only ever produce a dead "Check for updates" button.
    assert item["repository"] == ""


def test_list_backfills_repository_for_preexisting_installs(isolate):
    """Extensions installed before the update feature (no `repository` key) get it
    read from their unpacked manifest.json once, then persisted."""
    ext_dir = isolate / "extensions" / "old_ext"
    ext_dir.mkdir(parents=True)
    (ext_dir / "manifest.json").write_text(json.dumps(
        {"name": "Old Ext", "repository": "https://github.com/acme/old-ext"}))
    integrations._save_mcp_servers([{
        "id": "old_ext", "name": "Old Ext", "transport": "stdio", "command": "${PYTHON}",
        "args": [], "env": {}, "tools": [], "status": "connected", "detail": "",
        "source": "mcpb", "dir": str(ext_dir), "version": "0.9",
    }])
    listed = integrations.list_mcp_servers()
    assert listed[0]["repository"] == "https://github.com/acme/old-ext"
    # Persisted — the manifest read happens once, not on every list.
    assert integrations._find_mcp("old_ext")["repository"] == "https://github.com/acme/old-ext"


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
