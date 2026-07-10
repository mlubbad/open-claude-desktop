"""Route-layer coverage for the marketplace/skills/auth-flows endpoints — the branches
the domain-level tests don't exercise: the remote-disabled 403 gate, the multipart
zip-import upload path, and the auth-flows listing.
"""
import io
import zipfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(db):
    from app.main import app
    return TestClient(app)


def test_marketplace_add_source_403_when_remote_disabled(client, monkeypatch):
    from ocd_core import config
    monkeypatch.setattr(config, "MARKETPLACE_ALLOW_REMOTE", False)
    r = client.post("/marketplace/sources", json={"url": "https://github.com/x/y.git"})
    assert r.status_code == 403


def test_skills_from_repo_403_when_remote_disabled(client, monkeypatch):
    from ocd_core import config
    monkeypatch.setattr(config, "MARKETPLACE_ALLOW_REMOTE", False)
    r = client.post("/skills/from-repo", json={"url": "https://github.com/x/y.git"})
    assert r.status_code == 403


def test_auth_flows_route_lists_flows(client):
    r = client.get("/auth-flows")
    assert r.status_code == 200
    body = r.json()
    assert "enabled" in body and isinstance(body["flows"], list)
    # The known login flows are always listed (each flagged for CLI availability).
    assert any(f["id"] == "gcloud-adc" for f in body["flows"])


def test_skills_import_zip_route_extracts_and_imports(client, monkeypatch, tmp_path):
    from ocd_core import config
    monkeypatch.setattr(config, "SKILLS_DIR", tmp_path / "skills")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("seo-audit/SKILL.md",
                    "---\nname: seo-audit\ndescription: SEO\n---\nAudit the site.")
        zf.writestr("seo-audit/references/notes.md", "name: notes\n\nreference material")
    r = client.post(
        "/skills/import-zip",
        files={"file": ("bundle.zip", buf.getvalue(), "application/zip")},
    )
    assert r.status_code == 200
    assert "seo-audit" in r.json().get("names", [])
    # references/ is ignored — only the SKILL.md becomes a skill.
    assert "notes" not in {s["name"] for s in client.get("/skills").json()}


def test_add_mcp_server_bounds_discovery_timeout(tmp_path, monkeypatch):
    """P4: the interactive add path caps discovery at MCP_ADD_TIMEOUT_SEC (not the ~70s
    per-call default) so a hung server can't tie up the request; a timeout registers as
    an error the user can retry, not a silent hang."""
    from ocd_core import config, integrations, mcp_registry
    monkeypatch.setattr(integrations, "MCP_FILE", tmp_path / "mcp.json")
    monkeypatch.setattr(config, "MCP_ADD_TIMEOUT_SEC", 3)
    seen = {}

    def fake_discover(cfg, timeout=None):
        seen["timeout"] = timeout
        raise TimeoutError()

    monkeypatch.setattr(mcp_registry.registry, "discover", fake_discover)
    res = integrations.add_mcp_server("Slow", command="sleep", args=["9999"])
    assert seen["timeout"] == 3          # bounded, not the 60s default
    assert res["status"] == "error"
    assert "timed out" in res["detail"]  # honest, actionable message (no false "connected")
