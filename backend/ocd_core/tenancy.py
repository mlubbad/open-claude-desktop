"""Workspace tenancy: the keystone of the hosted-SaaS track.

The desktop app is single-user and local-first, so tenancy is OFF by default and
this whole module is a no-op: `enforcing()` is False, every row stays visible, and
new rows keep their historical NULL `workspace_id`. Nothing about the packaged app
changes byte-for-byte.

Flip `OCD_MULTI_TENANT=1` (a hosted multi-tenant deployment) and every project /
conversation read, write, list, and delete is scoped to the *current workspace* —
resolved per request (see `resolve_workspace`) and carried through the call stack in
a ``ContextVar`` so `ocd_core` domain functions never need a workspace argument
threaded through their signatures.

Migration story: rows written before tenancy was enabled have `workspace_id IS NULL`.
Those legacy rows belong to the implicit ``local`` workspace, so a single-user DB that
later turns tenancy on keeps working with zero data migration — its owner still sees
everything, while a *new* workspace sees only what it created.

Env is read at call time (via `enforcing()`) so tests and config apply without reimport.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

# The implicit workspace for the local-first desktop and for legacy (pre-tenancy) rows.
LOCAL_WORKSPACE = "local"

_workspace: ContextVar[str] = ContextVar("ocd_workspace", default=LOCAL_WORKSPACE)


class WorkspaceForbidden(Exception):
    """A mutation targeted a row owned by a different workspace. Routes map this to 404
    (indistinguishable from not-found) so cross-workspace existence never leaks."""


def enforcing() -> bool:
    """True only when multi-tenant scoping is switched on. Default OFF → the desktop app
    and any single-user server behave exactly as before."""
    return os.getenv("OCD_MULTI_TENANT", "").strip().lower() in ("1", "true", "yes", "on")


def current_workspace() -> str:
    return _workspace.get()


def set_current_workspace(ws: str) -> Token:
    """Set the current workspace; returns a token for `reset_current_workspace`."""
    return _workspace.set(ws or LOCAL_WORKSPACE)


def reset_current_workspace(token: Token) -> None:
    _workspace.reset(token)


@contextmanager
def use_workspace(ws: str) -> Iterator[None]:
    """Scope a block of `ocd_core` calls to a workspace (handy in tests and background
    jobs that run outside a request)."""
    token = set_current_workspace(ws)
    try:
        yield
    finally:
        reset_current_workspace(token)


def resolve_workspace(headers) -> str:
    """The workspace for an incoming request. Local (no enforcement) → always ``local``.

    Enforcing → an AUTHENTICATED identity is authoritative and cannot be overridden by a
    client header: a valid bearer resolves to its principal, whose workspace claim (a
    hosted OIDC/JWT token) scopes the request, or whose user id is their personal
    workspace (the MVP, and the HMAC login which carries no workspace). Only when there is
    NO authenticated identity do we fall back to an explicit ``X-OCD-Workspace`` header —
    for dev/testing, or a trusted reverse proxy that authenticates upstream and injects
    it. Otherwise ``local``."""
    if not enforcing():
        return LOCAL_WORKSPACE
    authz = headers.get("authorization", "") or ""
    if authz.lower().startswith("bearer "):
        from . import auth  # lazy: keep this module import-light
        principal = auth.identify(authz[7:].strip())
        if principal:
            # The token's own workspace can't be overridden by a header → no tenant escape.
            return principal.workspace or principal.user
    explicit = (headers.get("x-ocd-workspace") or "").strip()
    if explicit:
        return explicit
    return LOCAL_WORKSPACE


# --- scoping primitives used by the domain modules ------------------------------------
#
# All three are no-ops when enforcement is off, so the local single-user path keeps its
# exact prior behaviour (no filtering, NULL workspace_id on new rows).

def owns(workspace_value: str | None) -> bool:
    """Whether a row with `workspace_value` is visible to the current workspace. Legacy
    NULL rows belong to ``local`` (see the migration story above)."""
    if not enforcing():
        return True
    ws = current_workspace()
    if workspace_value == ws:
        return True
    return ws == LOCAL_WORKSPACE and workspace_value is None


def require_owned(workspace_value: str | None) -> None:
    """Guard for by-id mutations: raise `WorkspaceForbidden` when the target row belongs
    to another workspace (used where a not-found return can't express the denial)."""
    if not owns(workspace_value):
        raise WorkspaceForbidden()


def scope_clause(column):
    """A SQLAlchemy WHERE clause scoping `column` (a ``workspace_id`` column) to the
    current workspace, or None when enforcement is off (caller adds nothing)."""
    if not enforcing():
        return None
    ws = current_workspace()
    if ws == LOCAL_WORKSPACE:
        # local also owns legacy NULL-workspace rows.
        return (column == ws) | (column.is_(None))
    return column == ws


def stamp(obj) -> None:
    """Tag a freshly-created row with the current workspace (and owner) when enforcing.
    A no-op locally, so new rows keep the historical NULL `workspace_id`."""
    if enforcing():
        ws = current_workspace()
        obj.workspace_id = ws
        # owner_id mirrors the workspace for the one-workspace-per-user MVP; kept distinct
        # so a future many-users-per-workspace model can diverge without a schema change.
        if getattr(obj, "owner_id", None) is None:
            obj.owner_id = ws


def namespace() -> str | None:
    """A stable per-workspace namespace for keying tenant-scoped stores that live OUTSIDE
    the SQL row model — keychain secrets, the settings file, vector collections.

    Returns the workspace id for a non-local workspace under enforcement, else None. None
    means "use the historical, unscoped name": the local-first desktop (flag off) and the
    implicit `local` workspace both keep their pre-tenancy keys/files/collections, exactly
    like NULL-workspace SQL rows belong to `local`. So enabling tenancy never strands the
    single-user data already on disk, and two real workspaces can't read each other's."""
    if enforcing() and current_workspace() != LOCAL_WORKSPACE:
        return current_workspace()
    return None
