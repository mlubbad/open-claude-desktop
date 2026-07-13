"""Pluggable OIDC/JWT identity (SaaS slice 4a).

A hosted deployment trusts an external issuer whose JWT carries the user and a workspace
claim; `auth.identify` verifies it (stdlib HS256 / cryptography RS256, no PyJWT, no
network) and `tenancy.resolve_workspace` scopes the request to the token's workspace.
The authenticated workspace is AUTHORITATIVE — a client header can't override it. Off by
default (no JWT env) → the built-in HMAC login is unchanged.
"""
import base64
import hashlib
import hmac
import json
import time

from fastapi.testclient import TestClient
from ocd_core import auth, tenancy
from starlette.datastructures import Headers


def _b64(d: bytes) -> str:
    return base64.urlsafe_b64encode(d).rstrip(b"=").decode()


def _hs256(claims: dict, secret: str, alg: str = "HS256") -> str:
    h = _b64(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    p = _b64(json.dumps(claims).encode())
    sig = hmac.new(secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{_b64(sig)}"


def _soon() -> int:
    return int(time.time()) + 60


# ---- identify() -----------------------------------------------------------------------

def test_jwt_enables_auth_and_extracts_user_and_workspace(monkeypatch):
    monkeypatch.setenv("OCD_JWT_SECRET", "topsecret")
    assert auth.auth_enabled() is True  # a JWT issuer counts as auth configured
    p = auth.identify(_hs256({"sub": "alice", "workspace": "acme", "exp": _soon()}, "topsecret"))
    assert p is not None and p.user == "alice" and p.workspace == "acme"


def test_jwt_rejects_bad_signature_expiry_and_garbage(monkeypatch):
    monkeypatch.setenv("OCD_JWT_SECRET", "s")
    assert auth.identify(_hs256({"sub": "a", "exp": _soon()}, "WRONG")) is None      # bad sig
    assert auth.identify(_hs256({"sub": "a", "exp": int(time.time()) - 1}, "s")) is None  # expired
    assert auth.identify("not.a.jwt") is None
    assert auth.identify(None) is None


def test_jwt_rejects_alg_none_and_algorithm_confusion(monkeypatch):
    monkeypatch.setenv("OCD_JWT_SECRET", "s")  # configured alg is HS256
    # alg=none, empty signature — the classic downgrade.
    h = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    p = _b64(json.dumps({"sub": "a", "exp": _soon()}).encode())
    assert auth.identify(f"{h}.{p}.") is None
    # A token claiming a different alg than configured is rejected outright.
    assert auth.identify(_hs256({"sub": "a", "exp": _soon()}, "s", alg="HS512")) is None


def test_jwt_custom_user_and_workspace_claims(monkeypatch):
    monkeypatch.setenv("OCD_JWT_SECRET", "s")
    monkeypatch.setenv("OCD_JWT_USER_CLAIM", "email")
    monkeypatch.setenv("OCD_JWT_WORKSPACE_CLAIM", "org")
    p = auth.identify(_hs256({"email": "bob@x.com", "org": "team7", "exp": _soon()}, "s"))
    assert p.user == "bob@x.com" and p.workspace == "team7"


def test_jwt_issuer_and_audience_are_enforced(monkeypatch):
    monkeypatch.setenv("OCD_JWT_SECRET", "s")
    monkeypatch.setenv("OCD_JWT_ISSUER", "https://idp")
    monkeypatch.setenv("OCD_JWT_AUDIENCE", "ocd")
    ok = _hs256({"sub": "a", "iss": "https://idp", "aud": "ocd", "exp": _soon()}, "s")
    assert auth.identify(ok).user == "a"
    assert auth.identify(_hs256({"sub": "a", "iss": "evil", "aud": "ocd", "exp": _soon()}, "s")) is None
    assert auth.identify(_hs256({"sub": "a", "iss": "https://idp", "aud": "x", "exp": _soon()}, "s")) is None


def test_rs256_verification_with_configured_public_key(monkeypatch):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    monkeypatch.setenv("OCD_JWT_ALG", "RS256")
    monkeypatch.setenv("OCD_JWT_PUBLIC_KEY", pub_pem)
    h = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    p = _b64(json.dumps({"sub": "dave", "workspace": "rsaco", "exp": _soon()}).encode())
    sig = key.sign(f"{h}.{p}".encode(), padding.PKCS1v15(), hashes.SHA256())
    principal = auth.identify(f"{h}.{p}.{_b64(sig)}")
    assert principal is not None and principal.user == "dave" and principal.workspace == "rsaco"
    # A token signed by a DIFFERENT key is rejected.
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    bad = other.sign(f"{h}.{p}".encode(), padding.PKCS1v15(), hashes.SHA256())
    assert auth.identify(f"{h}.{p}.{_b64(bad)}") is None


def test_hmac_login_still_resolves_through_identify(monkeypatch):
    monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "s")  # no JWT env → HMAC path
    tok = auth.make_token("carol", int(time.time()))
    p = auth.identify(tok)
    assert p.user == "carol" and p.workspace is None  # single-user login carries no workspace


# ---- resolve_workspace() --------------------------------------------------------------

def test_jwt_workspace_is_authoritative_over_header(monkeypatch):
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    monkeypatch.setenv("OCD_JWT_SECRET", "s")
    tok = _hs256({"sub": "alice", "workspace": "acme", "exp": _soon()}, "s")
    # A conflicting X-OCD-Workspace header must NOT let the caller escape their tenant.
    h = Headers({"authorization": f"Bearer {tok}", "x-ocd-workspace": "evil"})
    assert tenancy.resolve_workspace(h) == "acme"


def test_personal_workspace_when_token_has_no_workspace_claim(monkeypatch):
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    monkeypatch.setenv("OCD_JWT_SECRET", "s")
    tok = _hs256({"sub": "alice", "exp": _soon()}, "s")
    assert tenancy.resolve_workspace(Headers({"authorization": f"Bearer {tok}"})) == "alice"


def test_header_fallback_only_without_a_valid_identity(monkeypatch):
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    monkeypatch.setenv("OCD_JWT_SECRET", "s")
    # No bearer at all → header is the fallback (dev / trusted upstream proxy).
    assert tenancy.resolve_workspace(Headers({"x-ocd-workspace": "wsX"})) == "wsX"
    # Invalid bearer → no principal → header fallback (the request 401s at current_user).
    assert tenancy.resolve_workspace(
        Headers({"authorization": "Bearer garbage", "x-ocd-workspace": "wsX"})) == "wsX"


# ---- end-to-end through the route stack ----------------------------------------------

def test_route_scopes_to_the_jwt_workspace(db, monkeypatch):
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    monkeypatch.setenv("OCD_JWT_SECRET", "s")
    c = TestClient(__import__("app.main", fromlist=["app"]).app)
    tok_a = _hs256({"sub": "u", "workspace": "wsA", "exp": _soon()}, "s")
    tok_b = _hs256({"sub": "u", "workspace": "wsB", "exp": _soon()}, "s")

    made = c.post("/projects/general/conversations", json={"first_message": "hi"},
                  headers={"authorization": f"Bearer {tok_a}"}).json()
    cid = made["id"]
    # wsA (the token's tenant) sees it; wsB — a different token — does not.
    assert c.get(f"/projects/general/conversations/{cid}",
                 headers={"authorization": f"Bearer {tok_a}"}).status_code == 200
    assert c.get(f"/projects/general/conversations/{cid}",
                 headers={"authorization": f"Bearer {tok_b}"}).status_code == 404
    # An unauthenticated request is rejected outright (JWT auth is enabled).
    assert c.get(f"/projects/general/conversations/{cid}").status_code == 401
