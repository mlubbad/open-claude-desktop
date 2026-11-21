from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from ocd_core import tenancy, workspace_access
from pydantic import BaseModel

from ..deps import current_user, require_workspace_role

router = APIRouter(prefix="/workspaces")


class MembershipBody(BaseModel):
    user_id: str
    role: str


def _same_workspace(workspace_id: str) -> None:
    if workspace_id != tenancy.current_workspace():
        raise HTTPException(404, "workspace not found")


@router.get("/{workspace_id}/members")
def list_members(workspace_id: str, user: str = Depends(current_user)) -> list[dict]:
    _same_workspace(workspace_id)
    return workspace_access.list_memberships(workspace_id, actor_user=user)


@router.post("/{workspace_id}/members")
def set_member(
    workspace_id: str,
    body: MembershipBody,
    user: str = Depends(require_workspace_role("admin")),
) -> dict:
    _same_workspace(workspace_id)
    try:
        row = workspace_access.set_membership(
            workspace_id, body.user_id, body.role, actor_user=user
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"workspace_id": row.workspace_id, "user_id": row.user_id, "role": row.role}


@router.delete("/{workspace_id}/members/{user_id}")
def remove_member(
    workspace_id: str,
    user_id: str,
    user: str = Depends(require_workspace_role("admin")),
) -> dict:
    _same_workspace(workspace_id)
    if not workspace_access.remove_membership(workspace_id, user_id, actor_user=user):
        raise HTTPException(404, "membership not found")
    return {"ok": True}
