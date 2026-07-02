"""Authentication gate for the Open Claude Desktop Reflex app.

Sign-in is Google-only ("Sign in with Google"): the backend runs the OAuth
Authorization-Code flow, verifies the Google email, and mints the shared HMAC
session token (ocd_core.auth). This module gates pages on that token.

Behaviour:
  * If GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET and a signing secret
    are all configured, every page is gated: unauthenticated visitors are
    redirected to /login.
  * If they are NOT configured, auth is treated as disabled (open) and a
    warning is emitted at import time.

Token format (opaque to the client): base64url("<user>|<exp>|<hmac_sha256>").
"""
from __future__ import annotations

import os
import sys
import time

import reflex as rx

# Pure HMAC crypto lives in ocd_core.auth so the FastAPI backend can verify
# tokens without importing Reflex. Imported here for the UI auth gate.
from ocd_core.auth import (  # noqa: F401
    auth_enabled,
    make_token,
    verify_token,
)

from . import api_client

# Session lifetime (seconds). Default 7 days; override with AUTH_SESSION_TTL_SEC.
_TTL = int(os.getenv("AUTH_SESSION_TTL_SEC", str(7 * 24 * 3600)))
_COOKIE = "ocd_auth"


if not auth_enabled():
    print("[AUTH] WARNING: Reflex app auth is DISABLED (set GOOGLE_OAUTH_CLIENT_ID, "
          "GOOGLE_OAUTH_CLIENT_SECRET and APP_AUTH_SECRET to enable the login gate).",
          file=sys.stderr)


# --------------------------------------------------------------------------- #
#  Auth state
# --------------------------------------------------------------------------- #
class AuthState(rx.State):
    auth_token: str = rx.Cookie("", name=_COOKIE, max_age=_TTL, same_site="lax")

    @rx.var
    def is_authenticated(self) -> bool:
        """For UI conditionals (e.g. showing a logout button)."""
        if not auth_enabled():
            return True  # auth disabled => open (local dev)
        return verify_token(self.auth_token, int(time.time()))

    @rx.event
    def require_login(self):
        """FIRST on_load handler on every gated page. Applies the cookie token to
        the API client, then verifies it freshly (not via a cached computed var)
        so expiry is always enforced."""
        if self.auth_token:
            api_client.configure(token=self.auth_token)
        if auth_enabled() and not verify_token(self.auth_token, int(time.time())):
            return rx.redirect("/login")

    @rx.event
    def redirect_if_authed(self):
        """on_load for /login: skip the sign-in button if already signed in."""
        if auth_enabled() and verify_token(self.auth_token, int(time.time())):
            return rx.redirect("/")

    @rx.event
    def complete_login(self):
        """on_load for /auth/complete: read ?token= (minted by the backend after
        Google verified the email), persist it in the cookie, apply it to the API
        client, and land on the home page. No token => back to /login."""
        token = ""
        try:
            token = self.router.page.params.get("token", "")
        except Exception:
            token = ""
        if not token:
            return rx.redirect("/login")
        self.auth_token = token
        api_client.configure(token=token)
        return rx.redirect("/")

    @rx.event
    def do_logout(self):
        self.auth_token = ""
        api_client.configure(token=None)
        return rx.redirect("/login")


# --------------------------------------------------------------------------- #
#  Pages
# --------------------------------------------------------------------------- #
def login_page() -> rx.Component:
    return rx.center(
        rx.card(
            rx.vstack(
                rx.hstack(
                    rx.icon("lock", size=20),
                    rx.heading("Open Claude Desktop", size="5"),
                    spacing="2", align="center",
                ),
                rx.text("Sign in to continue", size="2", color="var(--gray-9)"),
                rx.link(
                    rx.button(
                        rx.icon("log-in", size=18),
                        "Sign in with Google",
                        size="3", width="100%",
                    ),
                    href=f"{api_client._BASE}/auth/google/login",
                    width="100%",
                ),
                spacing="3", width="320px",
            ),
            padding="28px",
        ),
        height="100vh", width="100%", background="var(--gray-1)",
    )


def complete_page() -> rx.Component:
    return rx.center(
        rx.vstack(
            rx.spinner(size="3"),
            rx.text("Signing you in…", size="2", color="var(--gray-9)"),
            spacing="3", align="center",
        ),
        height="100vh", width="100%", background="var(--gray-1)",
    )
