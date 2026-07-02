"""Unit tests for ocd_core.google_oauth — offline (no network, no real Google).
authorization_url() builds a string locally; token exchange + id_token verify
are monkeypatched."""
import importlib
from urllib.parse import parse_qs, urlparse

import pytest


def _fresh(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("OCD_OAUTH_REDIRECT_URI",
                       "http://localhost:8000/auth/google/callback")
    return importlib.reload(importlib.import_module("ocd_core.google_oauth"))


def test_build_auth_url_registers_one_time_state(monkeypatch):
    go = _fresh(monkeypatch)
    url = go.build_auth_url()
    assert url.startswith("https://accounts.google.com/o/oauth2/auth")
    assert "cid.apps.googleusercontent.com" in url
    assert "redirect_uri=http" in url
    state = parse_qs(urlparse(url).query)["state"][0]
    assert go.consume_state(state) is True    # valid once
    assert go.consume_state(state) is False   # one-time only


def test_consume_unknown_state_is_false(monkeypatch):
    go = _fresh(monkeypatch)
    assert go.consume_state("never-issued") is False


def test_exchange_code_returns_verified_email(monkeypatch):
    go = _fresh(monkeypatch)

    class _Creds:
        id_token = "fake-jwt"

    class _FakeFlow:
        credentials = _Creds()

        def fetch_token(self, code):
            assert code == "auth-code-123"

    monkeypatch.setattr(go, "_flow", lambda: _FakeFlow())
    monkeypatch.setattr(go._id_token, "verify_oauth2_token",
                        lambda tok, req, aud: {"email": "alice@example.com",
                                               "email_verified": True})
    assert go.exchange_code("auth-code-123") == "alice@example.com"


def test_exchange_code_rejects_unverified_email(monkeypatch):
    go = _fresh(monkeypatch)

    class _Creds:
        id_token = "fake-jwt"

    class _FakeFlow:
        credentials = _Creds()

        def fetch_token(self, code):
            pass

    monkeypatch.setattr(go, "_flow", lambda: _FakeFlow())
    monkeypatch.setattr(go._id_token, "verify_oauth2_token",
                        lambda tok, req, aud: {"email": "x@example.com",
                                               "email_verified": False})
    with pytest.raises(ValueError):
        go.exchange_code("auth-code-123")
