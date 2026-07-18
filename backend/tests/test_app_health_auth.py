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
    for k in ("APP_USERNAME", "APP_PASSWORD", "APP_AUTH_SECRET",
              "CHAINLIT_AUTH_SECRET", "AJ360_AUTH_SECRET",
              "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"):
        monkeypatch.delenv(k, raising=False)
    r = client.get("/settings")
    assert r.status_code == 200


def test_protected_route_requires_valid_token(monkeypatch):
    import time

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "sec")
    monkeypatch.setenv("APP_AUTH_SECRET", "s")
    from ocd_core import auth

    from backend.app.main import app
    c = TestClient(app)
    assert c.get("/settings").status_code == 401                     # no token
    tok = auth.make_token("alice@example.com", int(time.time()))
    r = c.get("/settings", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert c.get("/settings",
                 headers={"Authorization": "Bearer garbage"}).status_code == 401
