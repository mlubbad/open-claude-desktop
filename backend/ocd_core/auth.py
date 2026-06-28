"""Backend-usable HMAC session-token crypto for Open Claude Desktop.

These pure helpers were extracted VERBATIM from the Reflex login module
(``aj360_app/aj360_app/auth.py``) so the FastAPI backend can mint and verify
session tokens without importing Reflex. The Reflex module now re-imports
``make_token`` / ``verify_token`` / ``credentials_ok`` from here and keeps only
its ``AuthState`` / ``login_page`` UI.

Token format (opaque to the client): base64url("<user>|<exp>|<hmac_sha256>").
The HMAC is keyed by the auth secret; expiry is enforced on verify with a
constant-time comparison.

Env is read at call time so configuration and tests apply without reimport.

Auth secret resolution (back-compat): prefer ``APP_AUTH_SECRET``, then fall
back to ``CHAINLIT_AUTH_SECRET``, then ``AJ360_AUTH_SECRET``.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

# Session lifetime (seconds). Default 7 days; override with AUTH_SESSION_TTL_SEC.
_TTL = int(os.getenv("AUTH_SESSION_TTL_SEC", str(7 * 24 * 3600)))


def _secret() -> bytes:
    return (os.getenv("APP_AUTH_SECRET")
            or os.getenv("CHAINLIT_AUTH_SECRET")
            or os.getenv("AJ360_AUTH_SECRET") or "").encode()


def _expected_user() -> str:
    return os.getenv("APP_USERNAME", "")


def _expected_pass() -> str:
    return os.getenv("APP_PASSWORD", "")


def auth_enabled() -> bool:
    """True only when credentials AND a signing secret are all configured."""
    return bool(_expected_user() and _expected_pass() and _secret())


def _sign(username: str, exp: int) -> str:
    msg = f"{username}|{exp}".encode()
    return hmac.new(_secret(), msg, hashlib.sha256).hexdigest()


def make_token(username: str, now: int) -> str:
    """Mint a signed session token that expires at now + _TTL."""
    exp = now + _TTL
    raw = f"{username}|{exp}|{_sign(username, exp)}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_token(token: str, now: int | None = None) -> str | None:
    """Return the username IFF the token is well-formed, unexpired, and
    correctly signed; otherwise None.

    ``now`` defaults to the current wall-clock time so callers (e.g. the
    FastAPI auth dependency) need not thread a clock through every request.
    """
    if now is None:
        now = int(time.time())
    if not token or not _secret():
        return None
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        username, exp_s, sig = raw.split("|")
        exp = int(exp_s)
    except Exception:
        return None
    if exp < now:
        return None
    if not hmac.compare_digest(sig, _sign(username, exp)):
        return None
    return username


def verify_token(token: str, now: int) -> bool:
    """True iff the token is well-formed, unexpired, and correctly signed."""
    return decode_token(token, now) is not None


def credentials_ok(username: str, password: str) -> bool:
    """Constant-time credential check. Fail-closed when not configured."""
    eu, ep = _expected_user(), _expected_pass()
    if not eu or not ep:
        return False
    return (hmac.compare_digest(username or "", eu)
            and hmac.compare_digest(password or "", ep))
