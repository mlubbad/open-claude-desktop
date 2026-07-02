from __future__ import annotations

import os
import time

from fastapi import APIRouter
from fastapi.responses import RedirectResponse
from ocd_core import auth, google_oauth

router = APIRouter(prefix="/auth")


def _frontend_url() -> str:
    return os.getenv("OCD_FRONTEND_URL", "http://localhost:3000")


@router.get("/google/login")
def google_login() -> RedirectResponse:
    """Kick off the OAuth Authorization-Code flow -> redirect to Google consent."""
    return RedirectResponse(google_oauth.build_auth_url())


@router.get("/google/callback")
def google_callback(code: str = "", state: str = "") -> RedirectResponse:
    """Google redirects here. Validate the CSRF state, exchange the code for a
    verified email, mint the HMAC session token, and hand it to the frontend."""
    fe = _frontend_url()
    if not code or not google_oauth.consume_state(state):
        return RedirectResponse(f"{fe}/login?error=auth_failed")
    try:
        email = google_oauth.exchange_code(code)
    except Exception:
        return RedirectResponse(f"{fe}/login?error=auth_failed")
    token = auth.make_token(email, int(time.time()))
    return RedirectResponse(f"{fe}/auth/complete?token={token}")
