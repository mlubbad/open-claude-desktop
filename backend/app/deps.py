from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from ocd_core import auth, tenancy

_bearer = HTTPBearer(auto_error=False)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    """Optional auth: when disabled (no creds configured) -> 'anonymous'.
    When enabled (HMAC login OR an OIDC/JWT issuer) -> require a valid Bearer token,
    resolved to its principal, else 401."""
    if not auth.auth_enabled():
        return "anonymous"
    principal = auth.identify(creds.credentials) if creds else None
    if not principal:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing token")
    return principal.user


async def scope_workspace(request: Request) -> AsyncIterator[None]:
    """Bind the request's workspace into a ContextVar for the duration of the call so the
    domain layer (projects/conversations) can scope rows without a workspace argument.

    Registered as a GLOBAL dependency (see app.main). It MUST be an async generator: an
    async dependency runs in the request coroutine's context, so the ContextVar it sets is
    copied into the threadpool that executes sync route handlers — a sync generator
    dependency would run in a worker thread and the set would not propagate. A no-op
    locally (resolves to the ``local`` workspace)."""
    token = tenancy.set_current_workspace(tenancy.resolve_workspace(request.headers))
    try:
        yield
    finally:
        tenancy.reset_current_workspace(token)
