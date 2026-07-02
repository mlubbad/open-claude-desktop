"""Route tests for Google OAuth login/callback. No real Google: the state store
is seeded directly and exchange_code/build_auth_url are monkeypatched."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APP_AUTH_SECRET", "test-secret")
    monkeypatch.setenv("OCD_FRONTEND_URL", "http://localhost:3000")
    from backend.app.main import app
    return TestClient(app)


def test_login_redirects_to_google(client, monkeypatch):
    from ocd_core import google_oauth
    monkeypatch.setattr(google_oauth, "build_auth_url",
                        lambda: "https://accounts.google.com/o/oauth2/auth?x=1")
    r = client.get("/auth/google/login", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"].startswith("https://accounts.google.com/")


def test_callback_mints_token_and_redirects(client, monkeypatch):
    from ocd_core import auth, google_oauth
    google_oauth._PENDING_STATES.add("st8")
    monkeypatch.setattr(google_oauth, "exchange_code", lambda code: "alice@example.com")
    r = client.get("/auth/google/callback?code=abc&state=st8", follow_redirects=False)
    assert r.status_code in (302, 307)
    loc = r.headers["location"]
    assert loc.startswith("http://localhost:3000/auth/complete?token=")
    token = loc.split("token=", 1)[1]
    assert auth.decode_token(token) == "alice@example.com"


def test_callback_rejects_bad_state(client, monkeypatch):
    from ocd_core import google_oauth
    monkeypatch.setattr(google_oauth, "exchange_code", lambda code: "x@example.com")
    r = client.get("/auth/google/callback?code=abc&state=UNKNOWN", follow_redirects=False)
    assert r.headers["location"] == "http://localhost:3000/login?error=auth_failed"


def test_callback_handles_exchange_failure(client, monkeypatch):
    from ocd_core import google_oauth
    google_oauth._PENDING_STATES.add("st9")

    def _boom(code):
        raise ValueError("bad code")

    monkeypatch.setattr(google_oauth, "exchange_code", _boom)
    r = client.get("/auth/google/callback?code=abc&state=st9", follow_redirects=False)
    assert r.headers["location"] == "http://localhost:3000/login?error=auth_failed"
