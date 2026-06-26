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

import base64
import hashlib
import hmac
import os
import sys
import time

import reflex as rx

# Session lifetime (seconds). Default 7 days; override with AUTH_SESSION_TTL_SEC.
_TTL = int(os.getenv("AUTH_SESSION_TTL_SEC", str(7 * 24 * 3600)))
_COOKIE = "ocd_auth"


# --------------------------------------------------------------------------- #
#  Pure token / credential helpers (unit-tested in tests/test_auth.py)
#  Env is read at call time so configuration and tests apply without reimport.
# --------------------------------------------------------------------------- #
def _secret() -> bytes:
    return (os.getenv("CHAINLIT_AUTH_SECRET")
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


def verify_token(token: str, now: int) -> bool:
    """True iff the token is well-formed, unexpired, and correctly signed."""
    if not token or not _secret():
        return False
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        username, exp_s, sig = raw.split("|")
        exp = int(exp_s)
    except Exception:
        return False
    if exp < now:
        return False
    return hmac.compare_digest(sig, _sign(username, exp))


def credentials_ok(username: str, password: str) -> bool:
    """Constant-time credential check. Fail-closed when not configured."""
    eu, ep = _expected_user(), _expected_pass()
    if not eu or not ep:
        return False
    return (hmac.compare_digest(username or "", eu)
            and hmac.compare_digest(password or "", ep))


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
