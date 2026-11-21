"""Knowledge & connectors polish: P1-10 sandbox image selection, P1-11 per-file KB
delete/re-index, P1-12 per-tool connector toggles."""
import pytest
from ocd_core import integrations, knowledge


# --------------------------------------------------------------------------- #
#  P1-10 — sandbox image selection
# --------------------------------------------------------------------------- #
def test_sandbox_image_env_wins(monkeypatch):
    monkeypatch.setenv("CODE_EXEC_IMAGE", "my-image:1")
    assert integrations._sandbox_image() == "my-image:1"


def test_sandbox_image_probe_result_is_cached(monkeypatch):
    monkeypatch.delenv("CODE_EXEC_IMAGE", raising=False)
    monkeypatch.setattr(integrations, "_SANDBOX_IMAGE_CACHE", {"name": None})
    calls = {"n": 0}

    class _R:
        returncode = 0

    def probe(*a, **k):
        calls["n"] += 1
        return _R()

    import subprocess
    monkeypatch.setattr(subprocess, "run", probe)
    assert integrations._sandbox_image() == "ocd-sandbox:latest"
    assert integrations._sandbox_image() == "ocd-sandbox:latest"
    assert calls["n"] == 1  # probed once per process

    # No local sandbox image -> the stock slim image.
    monkeypatch.setattr(integrations, "_SANDBOX_IMAGE_CACHE", {"name": None})
    _R.returncode = 1
    assert integrations._sandbox_image() == "python:3.11-slim"


# --------------------------------------------------------------------------- #
#  P1-11 — per-file KB delete / re-index
# --------------------------------------------------------------------------- #
class _FakeCollection:
    def __init__(self):
        self.deleted: list[dict] = []
        self.upserts = 0

    def delete(self, where=None, **kw):
        self.deleted.append(where or {})

    def upsert(self, **kw):
        self.upserts += 1


@pytest.fixture
def kb(tmp_path, monkeypatch):
    from ocd_core import config
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    coll = _FakeCollection()
    monkeypatch.setattr(knowledge, "get_project_kb_collection", lambda pid: coll)
    kb_dir = tmp_path / "projects" / "p1" / "knowledge"
    kb_dir.mkdir(parents=True)
    (kb_dir / "notes.txt").write_text("alpha beta", encoding="utf-8")
    return coll, kb_dir


def test_delete_file_removes_file_and_purges_chunks(kb):
    coll, kb_dir = kb
    assert knowledge.delete_project_file("p1", "notes.txt") is True
    assert not (kb_dir / "notes.txt").exists()
    assert {"source": "notes.txt"} in coll.deleted
    # Idempotent-ish: a second delete reports not-found.
    assert knowledge.delete_project_file("p1", "notes.txt") is False


def test_delete_file_refuses_path_escape(kb):
    coll, kb_dir = kb
    outside = kb_dir.parent / "instructions.md"
    outside.write_text("secret", encoding="utf-8")
    assert knowledge.delete_project_file("p1", "../instructions.md") is False
    assert outside.exists()  # traversal neutralized (basename-only, jailed to kb dir)


def test_reindex_purges_then_reingests(kb):
    coll, kb_dir = kb
    chunks = knowledge.reindex_project_file("p1", "notes.txt")
    assert chunks >= 1
    assert {"source": "notes.txt"} in coll.deleted  # old chunks purged first
    assert coll.upserts >= 1
    assert knowledge.reindex_project_file("p1", "missing.txt") == -1


# --------------------------------------------------------------------------- #
#  P1-12 — per-tool connector toggles
# --------------------------------------------------------------------------- #
@pytest.fixture
def mcp_file(tmp_path, monkeypatch):
    f = tmp_path / "mcp_servers.json"
    monkeypatch.setattr(integrations, "MCP_FILE", f)
    monkeypatch.setattr(integrations, "_MCP_CACHE", {"mtime": None, "text": ""})
    integrations._save_mcp_servers([{
        "id": "fs", "name": "Filesystem", "transport": "stdio", "command": "npx",
        "tools": [{"name": "read_file", "description": "", "inputSchema": {}},
                  {"name": "delete_file", "description": "", "inputSchema": {}}],
    }])
    return f


def test_disabled_tool_leaves_the_assembly(mcp_file):
    assert len(integrations.mcp_tools(["fs"])) == 2
    server = integrations.set_mcp_tool_enabled("fs", "delete_file", False)
    assert server["disabled_tools"] == ["delete_file"]
    names = [t["function"]["name"] for t in integrations.mcp_tools(["fs"])]
    assert names == ["mcp_fs_read_file"]  # the disabled tool never reaches the model

    # The toggle persists and lists expose names + disabled set for the UI.
    listed = integrations.list_mcp_servers()[0]
    assert listed["tools"] == ["read_file", "delete_file"]
    assert listed["disabled_tools"] == ["delete_file"]

    # Re-enable restores it.
    integrations.set_mcp_tool_enabled("fs", "delete_file", True)
    assert len(integrations.mcp_tools(["fs"])) == 2


def test_toggle_unknown_server_is_none(mcp_file):
    assert integrations.set_mcp_tool_enabled("nope", "x", False) is None
