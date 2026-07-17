from __future__ import annotations

from collections.abc import AsyncIterator
import os

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from ocd_core import auth, tenancy, workspace_access

_bearer = HTTPBearer(auto_error=False)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    """Optional auth: when disabled (no creds configured) -> 'anonymous'.
    When enabled (HMAC login OR an OIDC/JWT issuer) -> require a valid Bearer token,
    resolved to its principal, else 401."""
    if not auth.auth_enabled():
        if not tenancy.enforcing():
            return "anonymous"
        # Header-selected workspaces exist only for explicit local integration tests and
        # trusted development proxies. Production tenancy cannot start without auth.
        dev_headers = os.getenv("OCD_ALLOW_DEV_WORKSPACE_HEADER", "").strip().lower()
        if dev_headers not in ("1", "true", "yes", "on"):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
        workspace_access.create_workspace(
            tenancy.current_workspace(), tenancy.current_workspace(), "anonymous"
        )
        return "anonymous"
    principal = auth.identify(creds.credentials) if creds else None
    if not principal:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing token")
    workspace = tenancy.current_workspace()
    # A single-user/HMAC principal owns its personal workspace. JWT workspaces require
    # an explicit persisted membership provisioned by an owner/admin.
    if principal.workspace is None and workspace == principal.user:
        workspace_access.create_workspace(workspace, workspace, principal.user)
    try:
        workspace_access.require_role(principal.user, "viewer", workspace=workspace)
    except workspace_access.WorkspaceRoleForbidden as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "workspace membership required") from e
    return principal.user


def require_workspace_role(minimum: str):
    """FastAPI dependency factory for role-gated mutations."""
    def dependency(user: str = Depends(current_user)) -> str:
        try:
            workspace_access.require_role(user, minimum)
        except workspace_access.WorkspaceRoleForbidden as e:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient workspace role") from e
        return user

    return dependency


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
