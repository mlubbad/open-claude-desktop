"""Tests for the Open Claude Desktop Reflex auth gate (C4).

Covers the pure token/credential helpers in aj360_app/aj360_app/auth.py
(loaded by file path so no Reflex app context is needed). Env is read at call
time, so credentials are configured here before exercising the helpers.

Run:  venv312\\Scripts\\python.exe tests/test_auth.py
or:   venv312\\Scripts\\python.exe -m pytest tests/test_auth.py
"""
import importlib.util
import os

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

os.environ["APP_USERNAME"] = "tester"
os.environ["APP_PASSWORD"] = "s3cret!"
os.environ["CHAINLIT_AUTH_SECRET"] = "unit-test-secret-key"
os.environ["AUTH_SESSION_TTL_SEC"] = "3600"


def _load_auth():
    spec = importlib.util.spec_from_file_location(
        "ocd_auth", os.path.join(_HERE, "aj360_app", "aj360_app", "auth.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


auth = _load_auth()
NOW = 1_700_000_000  # fixed reference time (TTL=3600 in env above)


def test_auth_enabled_when_configured():
    assert auth.auth_enabled() is True


def test_credentials_ok():
    assert auth.credentials_ok("tester", "s3cret!") is True
    assert auth.credentials_ok("tester", "wrong") is False
    assert auth.credentials_ok("nope", "s3cret!") is False
    assert auth.credentials_ok("", "") is False


def test_token_roundtrip_valid():
    t = auth.make_token("tester", NOW)
    assert auth.verify_token(t, NOW) is True
    assert auth.verify_token(t, NOW + 10) is True


def test_token_expired():
    t = auth.make_token("tester", NOW)
    assert auth.verify_token(t, NOW + 3600 + 1) is False


def test_token_tampered_signature():
    t = auth.make_token("tester", NOW)
    bad = t[:-2] + ("AA" if t[-2:] != "AA" else "BB")
    assert auth.verify_token(bad, NOW) is False


def test_empty_or_garbage_token():
    assert auth.verify_token("", NOW) is False
    assert auth.verify_token("not-a-real-token", NOW) is False


def test_fail_closed_when_unconfigured():
    saved = os.environ.pop("APP_USERNAME", None)
    try:
        assert auth.credentials_ok("tester", "s3cret!") is False
        assert auth.auth_enabled() is False
    finally:
        if saved is not None:
            os.environ["APP_USERNAME"] = saved


if __name__ == "__main__":
    funcs = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failures = []
    for f in funcs:
        try:
            f()
            print("PASS", f.__name__)
        except AssertionError as e:
            print("FAIL", f.__name__, e)
            failures.append(f.__name__)
    print("RESULT:", "ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}")
    raise SystemExit(1 if failures else 0)
