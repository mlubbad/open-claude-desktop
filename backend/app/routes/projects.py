from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from ocd_core import projects

from ..deps import current_user, require_workspace_role
from ..schemas import AllowlistBody, ProjectCreate, ProjectPatch, TextBody

router = APIRouter(prefix="/projects")


@router.get("")
def list_projects(view: str = "", archived: bool = False,
                  user: str = Depends(current_user)) -> list[dict]:
    rows = projects.list_projects(include_archived=archived)
    if view == "card":
        return [projects.project_card_view(p) for p in rows]
    return rows


@router.post("")
def create_project(body: ProjectCreate,
                   user: str = Depends(require_workspace_role("member"))) -> dict:
    return projects.create_project(body.name, body.description or "")


@router.get("/{pid}")
def get_project(pid: str, user: str = Depends(current_user)) -> dict:
    p = projects.get_project(pid)
    if not p:
        raise HTTPException(404, "not found")
    return p


@router.patch("/{pid}")
def patch_project(pid: str, body: ProjectPatch,
                  user: str = Depends(require_workspace_role("member"))) -> dict:
    """Edit details (name/description) or toggle pinned/archived. Only sent fields change."""
    updated = projects.update_project(
        pid, name=body.name, description=body.description,
        pinned=body.pinned, archived=body.archived)
    if not updated:
        raise HTTPException(404, "not found")
    return updated


@router.delete("/{pid}")
def delete_project(pid: str, user: str = Depends(require_workspace_role("admin"))) -> dict:
    return {"ok": projects.delete_project(pid)}


@router.get("/{pid}/instructions")
def get_instructions(pid: str, user: str = Depends(current_user)) -> dict:
    return {"content": projects.get_project_instructions(pid)}


@router.put("/{pid}/instructions")
def put_instructions(pid: str, body: TextBody,
                     user: str = Depends(require_workspace_role("member"))) -> dict:
    projects.save_project_instructions(pid, body.content)
    return {"ok": True}


@router.get("/{pid}/memory")
def get_memory(pid: str, user: str = Depends(current_user)) -> dict:
    text, rel = projects.get_project_memory(pid)
    return {"content": text, "updated_rel": rel}


@router.put("/{pid}/memory")
def put_memory(pid: str, body: TextBody,
               user: str = Depends(require_workspace_role("member"))) -> dict:
    projects.save_project_memory(pid, body.content)
    return {"ok": True}


@router.get("/{pid}/allowlist")
def get_allowlist(pid: str, user: str = Depends(current_user)) -> dict:
    return {"tables": projects.get_project_allowlist(pid)}


@router.put("/{pid}/allowlist")
def put_allowlist(pid: str, body: AllowlistBody,
                  user: str = Depends(require_workspace_role("admin"))) -> dict:
    if not projects.save_project_allowlist(pid, body.tables):
        raise HTTPException(404, "not found")
    return {"ok": True}


@router.get("/{pid}/capacity")
def capacity(pid: str, user: str = Depends(current_user)) -> dict:
    return projects.project_capacity(pid)
