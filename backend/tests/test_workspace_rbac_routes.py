import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _token(user: str, workspace: str, secret: str = "rbac-secret") -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64(json.dumps({
        "sub": user,
        "workspace": workspace,
        "exp": int(time.time()) + 300,
    }).encode())
    sig = hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64(sig)}"


@pytest.fixture
def rbac(db, monkeypatch):
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    monkeypatch.setenv("OCD_JWT_SECRET", "rbac-secret")
    monkeypatch.setenv("OCD_JWT_ALG", "HS256")
    from ocd_core import workspace_access

    workspace_access.create_workspace("ws-a", "A", "alice")
    workspace_access.set_membership("ws-a", "bob", "viewer", actor_user="alice")
    workspace_access.set_membership("ws-a", "carol", "member", actor_user="alice")
    workspace_access.set_membership("ws-a", "dana", "admin", actor_user="alice")
    from app.main import app

    return TestClient(app)


def _headers(user: str, workspace: str = "ws-a") -> dict:
    return {"Authorization": f"Bearer {_token(user, workspace)}"}


def test_non_member_and_cross_workspace_token_are_forbidden(rbac):
    assert rbac.get("/projects", headers=_headers("mallory")).status_code == 403
    assert rbac.get("/projects", headers=_headers("alice", "ws-b")).status_code == 403


def test_viewer_can_read_but_cannot_create_or_mutate(rbac):
    assert rbac.get("/projects", headers=_headers("bob")).status_code == 200
    assert rbac.post("/projects", json={"name": "blocked"}, headers=_headers("bob")).status_code == 403
    assert rbac.post(
        "/schedules",
        json={"goal": "blocked", "kind": "interval", "every_seconds": 60},
        headers=_headers("bob"),
    ).status_code == 403


def test_member_can_create_work_but_not_administer_integrations(rbac):
    assert rbac.post("/projects", json={"name": "allowed"}, headers=_headers("carol")).status_code == 200
    assert rbac.post(
        "/connectors",
        json={"name": "blocked", "base_url": "https://example.com"},
        headers=_headers("carol"),
    ).status_code == 403


def test_admin_can_manage_integrations(rbac, monkeypatch):
    from ocd_core import integrations

    monkeypatch.setattr(integrations, "_safe_outbound_get", lambda *a, **k: None)
    response = rbac.post(
        "/connectors",
        json={"name": "allowed", "base_url": "https://example.com"},
        headers=_headers("dana"),
    )
    assert response.status_code == 200


def test_only_admin_or_owner_can_manage_memberships(rbac):
    body = {"user_id": "eve", "role": "viewer"}
    assert rbac.post("/workspaces/ws-a/members", json=body, headers=_headers("bob")).status_code == 403
    assert rbac.post("/workspaces/ws-a/members", json=body, headers=_headers("dana")).status_code == 200
    members = rbac.get("/workspaces/ws-a/members", headers=_headers("alice"))
    assert members.status_code == 200
    assert any(item["user_id"] == "eve" for item in members.json())
