"""Google OAuth2 (Authorization Code) helper for Open Claude Desktop.

Thin wrapper over google-auth-oauthlib. The backend stores no users: a
successful Google login mints the existing HMAC session token (ocd_core.auth),
which *is* the session. Any Google account with a verified email may sign in
(open register; no allowlist).

Config (read at call time, from .env):
  GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET  — the OAuth Web client
  OCD_OAUTH_REDIRECT_URI  — default http://localhost:8000/auth/google/callback

CSRF `state` is stored in-process (single-worker only — documented limitation).
"""
from __future__ import annotations

import os

from google.auth.transport import requests as _google_requests
from google.oauth2 import id_token as _id_token
from google_auth_oauthlib.flow import Flow

# Google returns `openid` (and reorders) scopes on exchange; relax oauthlib's
# strict scope-equality check. localhost callbacks are plain http, so allow it.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

# In-process one-time CSRF state store. Single-worker only.
_PENDING_STATES: set[str] = set()


def _client_id() -> str:
    return os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")


def _redirect_uri() -> str:
    return os.getenv("OCD_OAUTH_REDIRECT_URI",
                     "http://localhost:8000/auth/google/callback")


def _flow() -> Flow:
    # Permit http on localhost callbacks (dev). Harmless when the redirect is https.
    if _redirect_uri().startswith("http://"):
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
    client_config = {
        "web": {
            "client_id": _client_id(),
            "client_secret": os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", ""),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = Flow.from_client_config(client_config, scopes=_SCOPES)
    flow.redirect_uri = _redirect_uri()
    return flow


def build_auth_url() -> str:
    """Create an authorization URL, register its one-time CSRF state, return the URL."""
    flow = _flow()
    url, state = flow.authorization_url(
        access_type="offline", prompt="select_account",
        include_granted_scopes="true")
    _PENDING_STATES.add(state)
    return url


def consume_state(state: str) -> bool:
    """Validate + consume a one-time CSRF state. True iff it was pending."""
    try:
        _PENDING_STATES.remove(state)
        return True
    except KeyError:
        return False


def exchange_code(code: str) -> str:
    """Exchange an auth code for tokens, verify the returned id_token, and return
    the verified email. Raises ValueError when the email is missing/unverified."""
    flow = _flow()
    flow.fetch_token(code=code)
    info = _id_token.verify_oauth2_token(
        flow.credentials.id_token, _google_requests.Request(), _client_id())
    email = info.get("email")
    if not email or not info.get("email_verified"):
        raise ValueError("Google account has no verified email.")
    return email
