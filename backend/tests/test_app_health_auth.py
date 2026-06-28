import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from backend.app.main import app
    return TestClient(app)


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_auth_disabled_allows_unauthed(client, monkeypatch):
    monkeypatch.delenv("APP_USERNAME", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    r = client.get("/settings")
    assert r.status_code == 200


def test_login_and_protected_route(monkeypatch):
    monkeypatch.setenv("APP_USERNAME", "u")
    monkeypatch.setenv("APP_PASSWORD", "p")
    monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "s")
    from backend.app.main import app
    c = TestClient(app)
    assert c.get("/settings").status_code == 401          # no token
    tok = c.post("/auth/login", json={"username": "u", "password": "p"}).json()["token"]
    r = c.get("/settings", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert c.post("/auth/login", json={"username": "u", "password": "x"}).status_code == 401
