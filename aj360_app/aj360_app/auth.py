"""Authentication gate for the Open Claude Desktop Reflex app (C4).

The Reflex UI previously exposed the production-BigQuery agent (and the
sandboxed code-execution tools) with NO authentication. This module adds a
login gate that reuses the same credentials as the Chainlit app
(APP_USERNAME / APP_PASSWORD) and signs a session cookie with the existing
CHAINLIT_AUTH_SECRET.

Behaviour:
  * If APP_USERNAME, APP_PASSWORD and a signing secret are all configured,
    every page is gated: unauthenticated visitors are redirected to /login.
  * If they are NOT configured, auth is treated as disabled (open) — matching
    the Chainlit app's behaviour — and a warning is emitted at import time.

Token format (opaque to the client): base64url("<user>|<exp>|<hmac_sha256>").
The HMAC is keyed by the auth secret; expiry is enforced on verify with a
constant-time comparison.
"""
from __future__ import annotations

import os
import sys
import time

import reflex as rx

# Pure HMAC crypto now lives in ocd_core.auth so the FastAPI backend can verify
# tokens without importing Reflex. Imported here for backwards compatibility.
from ocd_core.auth import (  # noqa: F401
    auth_enabled,
    credentials_ok,
    make_token,
    verify_token,
)

# Session lifetime (seconds). Default 7 days; override with AUTH_SESSION_TTL_SEC.
_TTL = int(os.getenv("AUTH_SESSION_TTL_SEC", str(7 * 24 * 3600)))
_COOKIE = "ocd_auth"


if not auth_enabled():
    print("[AUTH] WARNING: Reflex app auth is DISABLED (set APP_USERNAME, "
          "APP_PASSWORD and CHAINLIT_AUTH_SECRET to enable the login gate).",
          file=sys.stderr)


# --------------------------------------------------------------------------- #
#  Auth state
# --------------------------------------------------------------------------- #
class AuthState(rx.State):
    auth_token: str = rx.Cookie("", name=_COOKIE, max_age=_TTL, same_site="lax")
    username: str = ""
    password: str = ""
    error: str = ""

    @rx.var
    def is_authenticated(self) -> bool:
        """For UI conditionals (e.g. showing a logout button)."""
        if not auth_enabled():
            return True  # auth disabled => open (matches Chainlit app)
        return verify_token(self.auth_token, int(time.time()))

    @rx.event
    def set_username(self, v: str):
        self.username = v

    @rx.event
    def set_password(self, v: str):
        self.password = v

    @rx.event
    def do_login(self):
        self.error = ""
        if credentials_ok(self.username, self.password):
            self.auth_token = make_token(self.username, int(time.time()))
            self.password = ""
            return rx.redirect("/")
        self.error = "Invalid username or password."

    @rx.event
    def do_logout(self):
        self.auth_token = ""
        self.username = ""
        self.password = ""
        return rx.redirect("/login")

    @rx.event
    def require_login(self):
        """FIRST on_load handler on every gated page. Verifies the token
        freshly (not via a cached computed var) so expiry is always enforced."""
        if auth_enabled() and not verify_token(self.auth_token, int(time.time())):
            return rx.redirect("/login")

    @rx.event
    def redirect_if_authed(self):
        """on_load for /login: skip the form if already signed in."""
        if auth_enabled() and verify_token(self.auth_token, int(time.time())):
            return rx.redirect("/")


# --------------------------------------------------------------------------- #
#  Login page
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
                rx.input(
                    placeholder="Username",
                    value=AuthState.username,
                    on_change=AuthState.set_username,
                    width="100%",
                ),
                rx.input(
                    placeholder="Password",
                    type="password",
                    value=AuthState.password,
                    on_change=AuthState.set_password,
                    width="100%",
                ),
                rx.cond(
                    AuthState.error != "",
                    rx.text(AuthState.error, color="var(--red-9)", size="2"),
                ),
                rx.button("Sign in", on_click=AuthState.do_login, width="100%"),
                spacing="3", width="320px",
            ),
            padding="28px",
        ),
        height="100vh", width="100%", background="var(--gray-1)",
    )
