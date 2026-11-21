"""Code workspace: file tree + read (traversal-jailed), and the /code routes."""
import pytest
from fastapi.testclient import TestClient
from ocd_core import integrations, workspace


@pytest.fixture
def ws(monkeypatch, tmp_path):
    """Point the sandbox root at a temp dir and seed a small project workspace."""
    monkeypatch.setattr(integrations, "SANDBOX_ROOT", tmp_path / "_sandbox")
    root = workspace.workspace_root("proj1")
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "README.md").write_text("# Hello\n", encoding="utf-8")
    (root / "node_modules").mkdir(exist_ok=True)
    (root / "node_modules" / "junk.js").write_text("noise", encoding="utf-8")
    return root


def test_list_tree_lists_files_and_skips_vendor_dirs(ws):
    entries = workspace.list_tree("proj1")
    paths = {e["path"]: e for e in entries}
    assert "README.md" in paths and paths["README.md"]["type"] == "file"
    assert "src" in paths and paths["src"]["type"] == "dir"
    assert "src/main.py" in paths
    # node_modules is skipped.
    assert not any("node_modules" in p for p in paths)


def test_read_file_returns_content(ws):
    r = workspace.read_file("proj1", "src/main.py")
    assert r["content"] == "print('hi')\n"
    assert r["binary"] is False and r["truncated"] is False


def test_read_file_rejects_traversal(ws, tmp_path):
    (tmp_path / "secret.txt").write_text("top secret", encoding="utf-8")
    r = workspace.read_file("proj1", "../../secret.txt")
    assert "error" in r
    assert "content" not in r


def test_read_missing_file(ws):
    r = workspace.read_file("proj1", "nope.py")
    assert r.get("error") == "not a file"


def test_binary_file_returns_no_text(ws):
    (ws / "img.bin").write_bytes(b"\x00\x01\x02\xff\xfe")
    r = workspace.read_file("proj1", "img.bin")
    assert r["binary"] is True and r["content"] == ""


def test_code_routes(ws):
    from app.main import app
    client = TestClient(app)
    tree = client.get("/code/tree", params={"project": "proj1"}).json()
    assert tree["project"] == "proj1"
    assert any(e["path"] == "src/main.py" for e in tree["entries"])
    got = client.get("/code/file", params={"project": "proj1", "path": "README.md"}).json()
    assert got["content"] == "# Hello\n"
    # Traversal via the route is jailed too.
    bad = client.get("/code/file", params={"project": "proj1", "path": "../../etc/passwd"}).json()
    assert "error" in bad
