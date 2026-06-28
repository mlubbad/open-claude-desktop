from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from ocd_core import projects

from ..deps import current_user
from ..schemas import AllowlistBody, ProjectCreate, TextBody

router = APIRouter(prefix="/projects")


@router.get("")
def list_projects(user: str = Depends(current_user)) -> list[dict]:
    return projects.list_projects()


@router.post("")
def create_project(body: ProjectCreate, user: str = Depends(current_user)) -> dict:
    return projects.create_project(body.name)


@router.get("/{pid}")
def get_project(pid: str, user: str = Depends(current_user)) -> dict:
    p = projects.get_project(pid)
    if not p:
        raise HTTPException(404, "not found")
    return p


@router.delete("/{pid}")
def delete_project(pid: str, user: str = Depends(current_user)) -> dict:
    return {"ok": projects.delete_project(pid)}


@router.get("/{pid}/instructions")
def get_instructions(pid: str, user: str = Depends(current_user)) -> dict:
    return {"content": projects.get_project_instructions(pid)}


@router.put("/{pid}/instructions")
def put_instructions(pid: str, body: TextBody, user: str = Depends(current_user)) -> dict:
    projects.save_project_instructions(pid, body.content)
    return {"ok": True}


@router.get("/{pid}/memory")
def get_memory(pid: str, user: str = Depends(current_user)) -> dict:
    text, rel = projects.get_project_memory(pid)
    return {"content": text, "updated_rel": rel}


@router.put("/{pid}/memory")
def put_memory(pid: str, body: TextBody, user: str = Depends(current_user)) -> dict:
    projects.save_project_memory(pid, body.content)
    return {"ok": True}


@router.get("/{pid}/allowlist")
def get_allowlist(pid: str, user: str = Depends(current_user)) -> dict:
    return {"tables": projects.get_project_allowlist(pid)}


@router.put("/{pid}/allowlist")
def put_allowlist(pid: str, body: AllowlistBody, user: str = Depends(current_user)) -> dict:
    if not projects.save_project_allowlist(pid, body.tables):
        raise HTTPException(404, "not found")
    return {"ok": True}


@router.get("/{pid}/capacity")
def capacity(pid: str, user: str = Depends(current_user)) -> dict:
    return projects.project_capacity(pid)
