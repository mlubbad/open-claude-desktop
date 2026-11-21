"""Unit tests for ocd_core.auth — the backend-usable HMAC crypto extracted
verbatim from the Reflex legacy_frontend.auth module.

NOTE on assertion adjustments vs. the task's reference test:
The REAL extracted functions are the contract, so these assertions were
adjusted to match the verbatim behaviour:
  * ``make_token`` / ``verify_token`` take an explicit ``now: int`` second
    argument (the Reflex caller passes ``int(time.time())``); they are NOT
    1-arg helpers.
  * ``verify_token`` returns a *bool* (well-formed + unexpired + correctly
    signed), NOT the decoded username.
  * ``auth_enabled`` requires APP_USERNAME *and* APP_PASSWORD *and* a signing
    secret to all be set (fail-closed), so the "disabled" test only needs to
    clear the secret/credentials to assert False, and the credential tests set
    the secret as well.
"""
import importlib


def test_token_roundtrip_and_tamper(monkeypatch):
    monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "test-secret")
    a = importlib.reload(importlib.import_module("ocd_core.auth"))
    now = 1_000_000
    tok = a.make_token("alice", now)
    # valid (unexpired) -> True
    assert a.verify_token(tok, now + 10) is True
    # tampered token -> False
    assert a.verify_token(tok + "x", now + 10) is False
    # garbage / not a real token -> False
    assert a.verify_token("not.a.token", now + 10) is False
    # expired -> False
    assert a.verify_token(tok, now + 10**9) is False


def test_credentials_ok(monkeypatch):
    monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "test-secret")
    monkeypatch.setenv("APP_USERNAME", "u")
    monkeypatch.setenv("APP_PASSWORD", "p")
    a = importlib.reload(importlib.import_module("ocd_core.auth"))
    assert a.credentials_ok("u", "p") is True
    assert a.credentials_ok("u", "wrong") is False


def test_auth_disabled_when_unset(monkeypatch):
    monkeypatch.delenv("APP_USERNAME", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    monkeypatch.delenv("CHAINLIT_AUTH_SECRET", raising=False)
    monkeypatch.delenv("OCD_AUTH_SECRET", raising=False)
    monkeypatch.delenv("APP_AUTH_SECRET", raising=False)
    a = importlib.reload(importlib.import_module("ocd_core.auth"))
    assert a.auth_enabled() is False


def test_decode_token_returns_username(monkeypatch):
    import time
    monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "s")
    a = importlib.reload(importlib.import_module("ocd_core.auth"))
    now = int(time.time())
    tok = a.make_token("alice", now)
    assert a.decode_token(tok, now) == "alice"
    assert a.decode_token(tok, now + 10**9) is None      # expired
    assert a.decode_token(tok + "x", now) is None         # tampered
    assert a.decode_token("garbage", now) is None
    assert a.decode_token(tok) == "alice"                 # now defaults to time.time()


def test_app_auth_secret_preferred_over_chainlit(monkeypatch):
    """Back-compat: APP_AUTH_SECRET is preferred, CHAINLIT_AUTH_SECRET is the
    fallback. A token minted under APP_AUTH_SECRET must verify under it."""
    monkeypatch.setenv("APP_AUTH_SECRET", "new-secret")
    monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "old-secret")
    a = importlib.reload(importlib.import_module("ocd_core.auth"))
    now = 2_000_000
    tok = a.make_token("bob", now)
    assert a.verify_token(tok, now + 10) is True
