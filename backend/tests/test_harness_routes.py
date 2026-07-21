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
from ocd_core import config
from ocd_core import workspace_registry as wr
from ocd_core.harness import checkpoints


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(wr, "_STORE", tmp_path / "workspaces.json")
    return TestClient(app)


def test_register_workspace(client, tmp_path):
    (tmp_path / "proj").mkdir()
    r = client.post("/harness/workspaces", json={"root": str(tmp_path / "proj")})
    assert r.status_code == 200
    assert r.json()["id"]


def test_list_recents(client, tmp_path):
    (tmp_path / "a").mkdir()
    client.post("/harness/workspaces", json={"root": str(tmp_path / "a")})
    r = client.get("/harness/workspaces")
    assert r.status_code == 200 and isinstance(r.json(), list)


def test_set_rules(client, tmp_path):
    (tmp_path / "p").mkdir()
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


def test_register_workspace_nonexistent_root_is_400(client, tmp_path):
    r = client.post("/harness/workspaces", json={"root": str(tmp_path / "does-not-exist")})
    assert r.status_code == 400


def test_register_workspace_file_root_is_400(client, tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")
    r = client.post("/harness/workspaces", json={"root": str(f)})
    assert r.status_code == 400


def test_set_rules_rejects_invalid_syntax(client, tmp_path):
    (tmp_path / "p2").mkdir()
    wid = client.post("/harness/workspaces", json={"root": str(tmp_path / "p2")}).json()["id"]
    r = client.put(f"/harness/workspaces/{wid}/rules",
                   json={"allow": ["!!!not(a(valid=rule"], "deny": [], "ask": []})
    assert r.status_code == 422


def test_checkpoint_list_and_restore(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("orig\n")
    # Turn-agnostic store root -- matches routes/harness.py's _store() AND the real
    # agent.py Task 14 wiring (agent.py:1397, CheckpointStore(config.REPO_ROOT /
    # "checkpoints")); turn_id is the checkpoint_id, not part of the store root. (The
    # plan's own Step 1 snippet still nested an extra "t1" segment into the
    # CheckpointStore root here -- inconsistent with its OWN corrected Step 3 route
    # code, which would never find a checkpoint written that way. Fixed to match Step 3.)
    store = checkpoints.CheckpointStore(tmp_path / "checkpoints")
    store.snapshot_before_edit("t1", ws, "a.txt")
    (ws / "a.txt").write_text("changed\n")

    wid = client.post("/harness/workspaces", json={"root": str(ws)}).json()["id"]
    lst = client.get(f"/harness/workspaces/{wid}/checkpoints/t1")
    assert lst.status_code == 200 and lst.json()[0]["files"] == ["a.txt"]

    r = client.post(f"/harness/workspaces/{wid}/checkpoints/t1/restore", json={"what": "files"})
    assert r.status_code == 200
    assert (ws / "a.txt").read_text() == "orig\n"


def test_checkpoint_list_unknown_workspace_is_404(client):
    r = client.get("/harness/workspaces/nope/checkpoints/t1")
    assert r.status_code == 404


def test_checkpoint_restore_unknown_workspace_is_404(client):
    r = client.post("/harness/workspaces/nope/checkpoints/t1/restore", json={"what": "files"})
    assert r.status_code == 404


def test_checkpoint_list_empty_turn_is_empty_list(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    (tmp_path / "ws2").mkdir()
    wid = client.post("/harness/workspaces", json={"root": str(tmp_path / "ws2")}).json()["id"]
    r = client.get(f"/harness/workspaces/{wid}/checkpoints/unknown-turn")
    assert r.status_code == 200 and r.json() == []


def test_checkpoint_restore_rejects_cross_workspace(client, tmp_path, monkeypatch):
    """CRITICAL fix: a checkpoint produced by workspace A must not be restorable into
    a DIFFERENT workspace B, even when both happen to share a turn_id and a same-named
    file (reproduced pre-fix: silently overwrote B's file with A's content)."""
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    ws_a = tmp_path / "ws_a"
    ws_a.mkdir()
    (ws_a / "shared.txt").write_text("A-orig\n")
    ws_b = tmp_path / "ws_b"
    ws_b.mkdir()
    (ws_b / "shared.txt").write_text("B-orig\n")

    store = checkpoints.CheckpointStore(tmp_path / "checkpoints")
    store.snapshot_before_edit("shared-turn", ws_a, "shared.txt")
    (ws_a / "shared.txt").write_text("A-changed\n")

    wid_a = client.post("/harness/workspaces", json={"root": str(ws_a)}).json()["id"]
    wid_b = client.post("/harness/workspaces", json={"root": str(ws_b)}).json()["id"]

    # B must NOT be able to restore A's checkpoint.
    r = client.post(f"/harness/workspaces/{wid_b}/checkpoints/shared-turn/restore",
                    json={"what": "files"})
    assert r.status_code == 404
    assert (ws_b / "shared.txt").read_text() == "B-orig\n"   # B left untouched

    # Listing a mismatched checkpoint reports nothing rather than leaking it.
    lst = client.get(f"/harness/workspaces/{wid_b}/checkpoints/shared-turn")
    assert lst.status_code == 200 and lst.json() == []

    # A can restore its own checkpoint.
    r = client.post(f"/harness/workspaces/{wid_a}/checkpoints/shared-turn/restore",
                    json={"what": "files"})
    assert r.status_code == 200
    assert (ws_a / "shared.txt").read_text() == "A-orig\n"


def test_restore_body_rejects_conversation(client):
    r = client.post("/harness/workspaces/nope/checkpoints/t1/restore",
                    json={"what": "conversation"})
    assert r.status_code == 422
