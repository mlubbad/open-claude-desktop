"""Workspace membership and role authorization.

Every multi-tenant caller must have a persisted membership. Role comparisons are
fail-closed; local single-user mode remains an implicit owner for compatibility.
"""
from __future__ import annotations

from sqlmodel import select

from . import tenancy
from .db import engine
from .db.models import Workspace, WorkspaceMembership, utcnow

ROLE_ORDER = {"viewer": 10, "member": 20, "admin": 30, "owner": 40}


class WorkspaceRoleForbidden(Exception):
    pass


def create_workspace(workspace_id: str, name: str, owner_user: str) -> Workspace:
    workspace_id = (workspace_id or "").strip()
    owner_user = (owner_user or "").strip()
    if not workspace_id or not owner_user:
        raise ValueError("workspace id and owner are required")
    with engine.session() as session:
        workspace = session.get(Workspace, workspace_id)
        if workspace is None:
            workspace = Workspace(id=workspace_id, name=name.strip() or workspace_id)
        else:
            workspace.name = name.strip() or workspace.name
            workspace.updated_at = utcnow()
        session.add(workspace)
        membership = session.get(WorkspaceMembership, (workspace_id, owner_user))
        if membership is None:
            membership = WorkspaceMembership(
                workspace_id=workspace_id, user_id=owner_user, role="owner"
            )
        else:
            membership.role = "owner"
            membership.updated_at = utcnow()
        session.add(membership)
    return workspace


def role_for(user_id: str, workspace: str | None = None) -> str | None:
    if not tenancy.enforcing():
        return "owner"
    workspace = workspace or tenancy.current_workspace()
    with engine.session() as session:
        row = session.get(WorkspaceMembership, (workspace, user_id))
        return row.role if row and row.role in ROLE_ORDER else None


def require_role(user_id: str, minimum: str = "viewer", *, workspace: str | None = None) -> str:
    if minimum not in ROLE_ORDER:
        raise ValueError(f"unknown workspace role {minimum!r}")
    role = role_for(user_id, workspace)
    if role is None or ROLE_ORDER[role] < ROLE_ORDER[minimum]:
        raise WorkspaceRoleForbidden()
    return role


def set_membership(
    workspace_id: str,
    user_id: str,
    role: str,
    *,
    actor_user: str,
) -> WorkspaceMembership:
    if role not in ROLE_ORDER:
        raise ValueError("invalid workspace role")
    actor_role = require_role(actor_user, "admin", workspace=workspace_id)
    if role == "owner" and actor_role != "owner":
        raise WorkspaceRoleForbidden()
    with engine.session() as session:
        if session.get(Workspace, workspace_id) is None:
            raise KeyError("workspace not found")
        membership = session.get(WorkspaceMembership, (workspace_id, user_id))
        if membership is None:
            membership = WorkspaceMembership(
                workspace_id=workspace_id, user_id=user_id, role=role
            )
        else:
            membership.role = role
            membership.updated_at = utcnow()
        session.add(membership)
    return membership


def remove_membership(workspace_id: str, user_id: str, *, actor_user: str) -> bool:
    actor_role = require_role(actor_user, "admin", workspace=workspace_id)
    with engine.session() as session:
        membership = session.get(WorkspaceMembership, (workspace_id, user_id))
        if membership is None:
            return False
        if membership.role == "owner" and actor_role != "owner":
            raise WorkspaceRoleForbidden()
        session.delete(membership)
        return True


def list_memberships(workspace_id: str, *, actor_user: str) -> list[dict]:
    require_role(actor_user, "viewer", workspace=workspace_id)
    with engine.session() as session:
        rows = session.exec(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == workspace_id)
            .order_by(WorkspaceMembership.user_id)
        ).all()
        return [{"workspace_id": row.workspace_id, "user_id": row.user_id, "role": row.role}
                for row in rows]
