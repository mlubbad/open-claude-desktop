"""Network-exposure guard — fail closed instead of fail open.

Phase 0 security fix (review finding C1). The backend historically fell OPEN to a
``anonymous`` user whenever no credentials were configured (``auth.auth_enabled()``
is False), which is the out-of-the-box default. Because privileged endpoints exist
(``POST /mcp-servers`` registers *and immediately executes* an arbitrary command),
a default deployment bound to a non-loopback interface is an unauthenticated RCE.

The product is **local-first, single-user** (architecture decision D3): the backend
is meant to run as a ``127.0.0.1`` sidecar behind the desktop shell. So the correct,
non-breaking fix is:

* Default the bind host to loopback (``127.0.0.1``).
* **Refuse to start** if the process is bound to a non-loopback interface or tenancy
  is enabled while authentication is disabled. No environment flag bypasses this.

This turns "default = open RCE on any interface" into "default = loopback-only (safe
for local-first) OR you must authenticate". All helpers are pure and unit-tested.
"""
from __future__ import annotations

import ipaddress
import os

from . import auth, tenancy

# The env var the run command / uvicorn invocation should honor for the bind host.
BIND_HOST_ENV = "OCD_BIND_HOST"
DEFAULT_BIND_HOST = "127.0.0.1"
# Development-mode launch-freeze carveout. It does not bypass authentication.
ALLOW_INSECURE_ENV = "OCD_ALLOW_INSECURE_NETWORK"

# Hostnames that are always treated as loopback without a DNS lookup.
_LOOPBACK_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}


def bind_host() -> str:
    """The interface the server should bind to (env-overridable, loopback default)."""
    return (os.getenv(BIND_HOST_ENV) or DEFAULT_BIND_HOST).strip() or DEFAULT_BIND_HOST


def is_loopback(host: str) -> bool:
    """True iff ``host`` refers only to the local machine.

    Accepts loopback literals (``127.0.0.0/8``, ``::1``), the well-known loopback
    hostnames, and the empty/whitespace host (treated as loopback — nothing to bind).
    A bare ``0.0.0.0`` / ``::`` (all interfaces) is explicitly NOT loopback.
    """
    h = (host or "").strip().strip("[]").split("%")[0]
    if not h:
        return True
    if h.lower() in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        # A non-literal hostname we can't classify offline — be conservative and
        # treat it as NOT loopback so an accidental public bind still fails closed.
        return False


def allow_insecure_network() -> bool:
    """Return the development launch-carveout flag (never an auth bypass)."""
    return os.getenv(ALLOW_INSECURE_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def authentication_required(host: str | None = None) -> bool:
    """Authentication is mandatory for tenancy or any non-loopback binding."""
    host = bind_host() if host is None else host
    return tenancy.enforcing() or not is_loopback(host)


def binding_is_safe(host: str | None = None) -> bool:
    """Whether it is safe to serve on ``host`` given the current auth configuration.

    Loopback single-user mode may remain unauthenticated. Every other mode requires auth.
    """
    host = bind_host() if host is None else host
    return not authentication_required(host) or auth.auth_enabled()


def unsafe_binding_reason(host: str | None = None) -> str | None:
    """Return a human-readable reason the binding is unsafe, or None if it is safe."""
    host = bind_host() if host is None else host
    if binding_is_safe(host):
        return None
    requirements = []
    if tenancy.enforcing():
        requirements.append("multi-tenant mode is enabled")
    if not is_loopback(host):
        requirements.append(f"the bind host '{host}' is non-loopback")
    context = " and ".join(requirements)
    return (
        f"Refusing to start because {context} while authentication is disabled. "
        "Authentication is mandatory in this mode; configure APP_USERNAME, "
        "APP_PASSWORD, and APP_AUTH_SECRET. For unauthenticated local development, "
        f"disable tenancy and bind {BIND_HOST_ENV}=127.0.0.1."
    )


def assert_safe_binding(host: str | None = None) -> None:
    """Abort startup (raise RuntimeError) if the binding is unsafe. No-op if safe."""
    reason = unsafe_binding_reason(host)
    if reason:
        raise RuntimeError(reason)
