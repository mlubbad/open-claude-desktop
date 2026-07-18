"""Fail-closed network/auth binding guard (shared by app.py and the backend).

Pure, stdlib-only. The point: refuse to serve an *unauthenticated* app on a
*non-loopback* interface (e.g. the Docker default ``--host 0.0.0.0``), which would
otherwise expose the agent -- and its BigQuery access -- to anyone who can reach
the port. Loopback binds and an explicit operator opt-out stay frictionless.
"""
from __future__ import annotations

import ipaddress
import os
import sys

# Chainlit's own default (chainlit.config.DEFAULT_HOST) -- loopback.
DEFAULT_HOST = "127.0.0.1"


def is_loopback_host(host: str) -> bool:
    """True if ``host`` binds only the loopback interface."""
    h = (host or "").strip().lower()
    if h == "localhost":
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def effective_bind_host(argv=None, env=None) -> str:
    """Best-effort resolution of the host the server will actually bind.

    Precedence matches how ``chainlit run`` resolves it: an explicit ``--host``
    CLI flag, then the ``CHAINLIT_HOST`` env var, then Chainlit's loopback default.
    """
    argv = sys.argv if argv is None else argv
    env = os.environ if env is None else env
    for i, a in enumerate(argv):
        if a == "--host" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--host="):
            return a.split("=", 1)[1]
    if env.get("CHAINLIT_HOST"):
        return env["CHAINLIT_HOST"]
    return DEFAULT_HOST


def require_authenticated_binding(*, auth_configured: bool, host: str,
                                  allow_unauthenticated: bool) -> None:
    """Raise ``RuntimeError`` when serving unauthenticated on a non-loopback host.

    No-op when auth is configured, when the bind is loopback, or when the operator
    has explicitly opted out (they front the app with their own authenticating proxy).
    """
    if auth_configured or allow_unauthenticated:
        return
    if is_loopback_host(host):
        return
    raise RuntimeError(
        f"Refusing to start: authentication is not configured and the server is "
        f"bound to a non-loopback host ({host!r}). Set APP_USERNAME and APP_PASSWORD "
        f"to enable login, bind to 127.0.0.1 for local-only use, or set "
        f"OCD_ALLOW_UNAUTHENTICATED=true if this app sits behind your own "
        f"authenticating proxy."
    )
