"""Harness routes: code-workspace CRUD/recents/rules.

NOTE (deviation from the plan): the plan specifies a bare "/workspaces" prefix, but
app/routes/workspaces.py already owns "/workspaces" for the unrelated TENANCY concept
(workspace membership). Mixing the harness folder-workspace into that namespace is
confusing and a latent collision risk, so these routes live under "/harness/workspaces"
instead -- see the module docstring in tests/test_harness_routes.py for the full
rationale.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from ocd_core import workspace_registry
from pydantic import BaseModel

from ..deps import current_user

router = APIRouter(prefix="/harness/workspaces")


class WorkspaceCreate(BaseModel):
    root: str


class RulesBody(BaseModel):
    allow: list[str] = []
    deny: list[str] = []
    ask: list[str] = []


@router.post("")
def create_workspace(body: WorkspaceCreate, user: str = Depends(current_user)) -> dict:
    return workspace_registry.register(body.root)


@router.get("")
def list_workspaces(user: str = Depends(current_user)) -> list[dict]:
    return workspace_registry.list_recents()


@router.get("/{wid}")
def get_workspace(wid: str, user: str = Depends(current_user)) -> dict:
    ws = workspace_registry.get(wid)
    if not ws:
        raise HTTPException(404, "unknown workspace")
    return ws


@router.put("/{wid}/rules")
def set_rules(wid: str, body: RulesBody, user: str = Depends(current_user)) -> dict:
    if not workspace_registry.get(wid):
        raise HTTPException(404, "unknown workspace")
    workspace_registry.set_rules(wid, body.model_dump())
    return {"ok": True}
