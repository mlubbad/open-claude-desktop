"""The mcp_servers.json mtime cache — call_mcp reads the registry on EVERY MCP tool
call, so the per-call disk read was a hot-path tax. The cache must be invisible:
fresh objects per call (callers mutate-then-save), invalidation on every write, and
corrupt files reading as empty."""
import json

from ocd_core import integrations


def _point_at(monkeypatch, tmp_path):
    f = tmp_path / "mcp_servers.json"
    monkeypatch.setattr(integrations, "MCP_FILE", f)
    monkeypatch.setattr(integrations, "_MCP_CACHE", {"mtime": None, "text": ""})
    return f


def test_cache_serves_without_rereading_disk(monkeypatch, tmp_path):
    f = _point_at(monkeypatch, tmp_path)
    f.write_text(json.dumps([{"id": "a", "name": "A"}]), encoding="utf-8")
    assert integrations._load_mcp_servers()[0]["id"] == "a"

    reads = {"n": 0}
    real_read = type(f).read_text

    def counting_read(self, *a, **k):
        reads["n"] += 1
        return real_read(self, *a, **k)

    monkeypatch.setattr(type(f), "read_text", counting_read)
    for _ in range(5):
        assert integrations._load_mcp_servers()[0]["id"] == "a"
    assert reads["n"] == 0  # mtime unchanged -> served from cache


def test_save_invalidates_the_cache(monkeypatch, tmp_path):
    _point_at(monkeypatch, tmp_path)
    integrations._save_mcp_servers([{"id": "a"}])
    assert [s["id"] for s in integrations._load_mcp_servers()] == ["a"]
    integrations._save_mcp_servers([{"id": "a"}, {"id": "b"}])
    assert [s["id"] for s in integrations._load_mcp_servers()] == ["a", "b"]


def test_callers_get_fresh_objects_each_call(monkeypatch, tmp_path):
    """A caller that mutates its copy and then fails before saving must not poison
    later reads — exactly the uncached semantics."""
    f = _point_at(monkeypatch, tmp_path)
    f.write_text(json.dumps([{"id": "a", "status": "connected"}]), encoding="utf-8")
    first = integrations._load_mcp_servers()
    first[0]["status"] = "error"  # mutated, never saved
    assert integrations._load_mcp_servers()[0]["status"] == "connected"


def test_missing_and_corrupt_files_read_as_empty(monkeypatch, tmp_path):
    f = _point_at(monkeypatch, tmp_path)
    assert integrations._load_mcp_servers() == []
    f.write_text("{not json", encoding="utf-8")
    assert integrations._load_mcp_servers() == []
    f.write_text('{"a": 1}', encoding="utf-8")  # valid JSON, wrong shape
    assert integrations._load_mcp_servers() == []
