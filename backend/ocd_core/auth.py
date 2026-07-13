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
import json
import os
import time
from dataclasses import dataclass

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


def _hmac_enabled() -> bool:
    """The built-in single-user login is configured (username + password + signing secret)."""
    return bool(_expected_user() and _expected_pass() and _secret())


def auth_enabled() -> bool:
    """True when ANY auth mode is configured: the built-in HMAC login, or an external
    OIDC/JWT issuer (a hosted deployment). Used to decide whether requests need a token
    and whether a non-loopback bind is safe (see netguard)."""
    return _hmac_enabled() or _jwt_enabled()


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


# ---------------------------------------------------------------------------------------
# Pluggable identity (hosted-SaaS): an authenticated principal → (user, workspace).
#
# The built-in HMAC login is single-user, so it never carries a workspace. A hosted
# deployment instead trusts an external OIDC/JWT issuer whose token carries the user
# (`sub`) and a tenant/workspace claim; `tenancy.resolve_workspace` reads that claim to
# scope the request. JWT verification is stdlib for HS256 and `cryptography` for RS256 —
# no PyJWT dependency, no network (JWKS fetch is a later extension). Env is read at call
# time so config/tests apply without reimport. Everything fails CLOSED.
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Principal:
    """An authenticated caller. `workspace` is the tenant to scope to (None → the caller's
    personal workspace, keyed by `user`)."""
    user: str
    workspace: str | None = None


def _jwt_secret() -> str:
    return os.getenv("OCD_JWT_SECRET", "")


def _jwt_public_key() -> str:
    # A PEM public key (RS256). Newlines may be escaped in env, so unescape them.
    return os.getenv("OCD_JWT_PUBLIC_KEY", "").replace("\\n", "\n")


def _jwt_enabled() -> bool:
    return bool(_jwt_secret() or _jwt_public_key())


def _jwt_alg() -> str:
    return os.getenv("OCD_JWT_ALG", "HS256").upper()


def _jwt_user_claim() -> str:
    return os.getenv("OCD_JWT_USER_CLAIM", "sub")


def _jwt_workspace_claim() -> str:
    return os.getenv("OCD_JWT_WORKSPACE_CLAIM", "workspace")


def _b64url_decode(seg: str) -> bytes:
    return base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))


def _verify_jwt_sig(alg: str, signing_input: bytes, sig: bytes) -> bool:
    if alg == "HS256":
        secret = _jwt_secret()
        if not secret:
            return False
        expected = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
        return hmac.compare_digest(expected, sig)
    if alg == "RS256":
        pub = _jwt_public_key()
        if not pub:
            return False
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
            serialization.load_pem_public_key(pub.encode()).verify(
                sig, signing_input, padding.PKCS1v15(), hashes.SHA256())
            return True
        except Exception:
            return False
    return False  # unsupported alg → fail closed


def _jwt_claims_ok(payload: dict, now: int) -> bool:
    exp = payload.get("exp")
    if exp is not None and now >= int(exp):
        return False
    nbf = payload.get("nbf")
    if nbf is not None and now < int(nbf):
        return False
    iss_want = os.getenv("OCD_JWT_ISSUER", "")
    if iss_want and payload.get("iss") != iss_want:
        return False
    aud_want = os.getenv("OCD_JWT_AUDIENCE", "")
    if aud_want:
        aud = payload.get("aud")
        auds = aud if isinstance(aud, list) else [aud]
        if aud_want not in auds:
            return False
    return True


def _verify_jwt(token: str, now: int | None = None) -> dict | None:
    """Verify a compact JWS and return its claims, or None on any failure."""
    if now is None:
        now = int(time.time())
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
        header = json.loads(_b64url_decode(header_b64))
        payload = json.loads(_b64url_decode(payload_b64))
        sig = _b64url_decode(sig_b64)
    except Exception:
        return None
    # Only accept the CONFIGURED algorithm — never trust the token's own `alg` header
    # (defeats the classic alg=none and HS/RS confusion attacks).
    if (header.get("alg") or "").upper() != _jwt_alg():
        return None
    if not _verify_jwt_sig(_jwt_alg(), f"{header_b64}.{payload_b64}".encode(), sig):
        return None
    if not isinstance(payload, dict) or not _jwt_claims_ok(payload, now):
        return None
    return payload


def identify(token: str | None, now: int | None = None) -> Principal | None:
    """Resolve a bearer token to a Principal, or None if it isn't valid. Uses the external
    OIDC/JWT issuer when one is configured, else the built-in HMAC session token."""
    if not token:
        return None
    if _jwt_enabled():
        claims = _verify_jwt(token, now)
        if not claims:
            return None
        user = str(claims.get(_jwt_user_claim()) or "").strip()
        if not user:
            return None
        ws = claims.get(_jwt_workspace_claim())
        return Principal(user=user, workspace=str(ws).strip() if ws else None)
    user = decode_token(token, now)
    return Principal(user=user) if user else None
