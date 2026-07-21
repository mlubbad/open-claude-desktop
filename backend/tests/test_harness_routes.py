"""Harness routes: workspace CRUD/recents/rules + checkpoint list/restore.

NOTE (naming collision, deviation from the plan): the plan's literal routes use a bare
"/workspaces" prefix, but app/routes/workspaces.py already owns that prefix for the
UNRELATED tenancy concept (workspace membership -- /workspaces/{workspace_id}/members).
Mixing the harness folder-workspace into that namespace is confusing and a latent
collision risk (e.g. a future tenancy `GET /workspaces/{id}` would shadow this route's
`GET /workspaces/{wid}`), so these routes live under "/harness/workspaces" instead.
"""
import pytest
from app.main import app
from fastapi.testclient import TestClient
from ocd_core import workspace_registry as wr


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(wr, "_STORE", tmp_path / "workspaces.json")
    return TestClient(app)


def test_register_workspace(client, tmp_path):
    r = client.post("/harness/workspaces", json={"root": str(tmp_path / "proj")})
    assert r.status_code == 200
    assert r.json()["id"]


def test_list_recents(client, tmp_path):
    client.post("/harness/workspaces", json={"root": str(tmp_path / "a")})
    r = client.get("/harness/workspaces")
    assert r.status_code == 200 and isinstance(r.json(), list)


def test_set_rules(client, tmp_path):
    wid = client.post("/harness/workspaces", json={"root": str(tmp_path / "p")}).json()["id"]
    r = client.put(f"/harness/workspaces/{wid}/rules",
                   json={"allow": ["bash(git *)"], "deny": [], "ask": []})
    assert r.status_code == 200
    assert client.get(f"/harness/workspaces/{wid}").json()["rules"]["allow"] == ["bash(git *)"]


def test_get_unknown_workspace_is_404(client):
    r = client.get("/harness/workspaces/nope")
    assert r.status_code == 404


def test_set_rules_unknown_workspace_is_404(client):
    r = client.put("/harness/workspaces/nope/rules", json={"allow": [], "deny": [], "ask": []})
    assert r.status_code == 404
