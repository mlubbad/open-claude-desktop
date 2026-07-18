"""Backend HMAC session-token crypto for Open Claude Desktop.

Identity is proven via Google OAuth (see ``ocd_core.google_oauth``); this module
only MINTS and VERIFIES the opaque HMAC session token that represents a logged-in
session. ``auth_enabled()`` reports whether the login gate is active (Google client
credentials + a signing secret all configured); when unconfigured, auth is open
(local dev). ``make_token`` / ``verify_token`` / ``decode_token`` are reused by both
the FastAPI backend (Bearer auth) and the Reflex UI gate.

Token format (opaque to the client): base64url("<user>|<exp>|<hmac_sha256>").
The HMAC is keyed by the auth secret; expiry is enforced on verify with a
constant-time comparison.

Env is read at call time so configuration and tests apply without reimport.

Auth secret resolution (back-compat): prefer ``APP_AUTH_SECRET``, then fall back
to ``CHAINLIT_AUTH_SECRET``, then ``OCD_AUTH_SECRET``, then ``AJ360_AUTH_SECRET``.
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
            or os.getenv("OCD_AUTH_SECRET")
            or os.getenv("AJ360_AUTH_SECRET") or "").encode()


def auth_enabled() -> bool:
    """True only when Google OAuth client credentials AND a signing secret are
    all configured. Unconfigured -> open (local dev), matching prior behaviour."""
    return bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID")
                and os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
                and _secret())


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
