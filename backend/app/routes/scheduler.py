"""Scheduler routes — CRUD for scheduled ("automation") Cowork tasks. The background
ticker in the app lifespan launches due schedules as autonomous Cowork tasks."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from ocd_core import scheduler
from pydantic import BaseModel

from ..deps import current_user, require_workspace_role

router = APIRouter()


class ScheduleBody(BaseModel):
    goal: str
    kind: str = "interval"                # "interval" | "daily"
    every_seconds: int | None = None
    at: str | None = None                 # "HH:MM" (UTC) for daily
    model: str = ""
    provider: str | None = None
    effort: str = "High"
    project_id: str | None = None


class EnabledBody(BaseModel):
    enabled: bool


@router.get("/schedules")
def list_schedules(user: str = Depends(current_user)) -> list[dict]:
    return scheduler.service.list()


@router.post("/schedules")
def add_schedule(body: ScheduleBody,
                 user: str = Depends(require_workspace_role("member"))) -> dict:
    if not body.goal.strip():
        raise HTTPException(status_code=400, detail="goal is required")
    if body.kind == "interval" and not (body.every_seconds and body.every_seconds > 0):
        raise HTTPException(status_code=400, detail="every_seconds must be > 0 for interval")
    if body.kind == "daily" and not body.at:
        raise HTTPException(status_code=400, detail="at (HH:MM) is required for daily")
    if body.kind not in ("interval", "daily"):
        raise HTTPException(status_code=400, detail="kind must be 'interval' or 'daily'")
    return scheduler.service.add(
        goal=body.goal, kind=body.kind, every_seconds=body.every_seconds, at=body.at,
        model=body.model, provider=body.provider, effort=body.effort,
        project_id=body.project_id)


@router.delete("/schedules/{sid}")
def remove_schedule(sid: str, user: str = Depends(require_workspace_role("admin"))) -> dict:
    if not scheduler.service.remove(sid):
        raise HTTPException(status_code=404, detail="no such schedule")
    return {"ok": True}


@router.post("/schedules/{sid}/enabled")
def set_enabled(sid: str, body: EnabledBody,
                user: str = Depends(require_workspace_role("member"))) -> dict:
    res = scheduler.service.set_enabled(sid, body.enabled)
    if res is None:
        raise HTTPException(status_code=404, detail="no such schedule")
    return res
