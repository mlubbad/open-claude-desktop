"""Cowork routes — delegate a task the agent runs autonomously in the background, then
list / inspect / cancel those tasks.

Approval mode (P1-8):
  * ``skip``   — permission_mode=auto, no reply channel: explicit autonomous opt-in.
  * ``manual`` — permission_mode=ask + a turn_id (default): the task pauses on sensitive actions
    and surfaces ``approval_required`` in its transcript; the task-detail view resolves
    it through the shared ``/agent/turn/{turn_id}/permission`` endpoint.

Background tasks get the full autonomous toolset — web, artifacts, memory, subagents,
AND the code/file tools (code_execution, bash, text_editor) so a delegated job can
actually build something in its workspace (previously it could only read/browse)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from ocd_core import agent, cowork, opik_tracing, settings
from pydantic import BaseModel, field_validator

from ..deps import current_user, require_workspace_role

router = APIRouter()


class CoworkStart(BaseModel):
    goal: str
    model: str
    provider: str | None = None
    effort: str = "High"
    project_id: str | None = None
    approval: str = "manual"   # skip (autonomous opt-in) | manual (default HITL gate)

    @field_validator("approval")
    @classmethod
    def _bound_approval(cls, v: str) -> str:
        # Empty/unset and typos resolve to the gated mode so a background job cannot
        # lose its HITL gate because of an omitted or malformed input.
        m = str(v or "").strip().lower()
        if m in {"skip", "manual"}:
            return m
        return "manual"


@router.post("/cowork")
async def start_task(body: CoworkStart,
                     user: str = Depends(require_workspace_role("member"))) -> dict:
    """Delegate a goal to a background agent task. Returns the task summary immediately."""
    if not body.goal.strip():
        raise HTTPException(status_code=400, detail="goal is required")
    # Global kill-switch: refuse to start new unattended work while autonomy is paused.
    if settings.get_settings().get("autonomy_paused"):
        raise HTTPException(status_code=409,
                            detail="autonomy is paused — new background tasks are blocked")

    manual = body.approval == "manual"
    turn_id = uuid.uuid4().hex if manual else None

    # 'manual' wires a live HITL gate (ask + turn_id) and gets the FULL toolset,
    # including the destructive code/file tools. 'skip' runs unattended with the gate
    # off, so it is restricted to read/browse/orchestrate tools — a background job
    # cannot silently run code/bash/text_editor off injected content. To build in the
    # background, choose 'manual'.
    tools = agent.background_tool_flags(gated=manual)

    def gen_factory():
        # The Opik tap (opt-in) mirrors the run into a trace without touching the stream.
        return opik_tracing.traced(
            agent.run_turn(
                body.goal, [], body.project_id, body.model,
                effort=body.effort, provider=body.provider,
                permission_mode=("ask" if manual else "auto"), turn_id=turn_id,
                **tools,
            ),
            goal=body.goal, model=body.model, provider=body.provider,
            effort=body.effort, turn_id=turn_id, tags=["cowork"],
        )

    task = cowork.manager.start(
        body.goal, gen_factory, approval=body.approval, turn_id=turn_id,
        project_id=body.project_id, model=body.model, provider=body.provider,
        effort=body.effort)
    return task.summary()


@router.get("/cowork")
def list_tasks(user: str = Depends(current_user)) -> list[dict]:
    return cowork.manager.list()


@router.post("/cowork/clear")
def clear_tasks(user: str = Depends(require_workspace_role("member"))) -> dict:
    """Drop all finished tasks (the 'Clear active' action). Running tasks are kept."""
    return {"cleared": cowork.manager.clear_finished()}


@router.get("/cowork/{task_id}")
def get_task(task_id: str, user: str = Depends(current_user)) -> dict:
    detail = cowork.manager.get(task_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="no such task")
    return detail


@router.post("/cowork/{task_id}/cancel")
def cancel_task(task_id: str, user: str = Depends(require_workspace_role("member"))) -> dict:
    if not cowork.manager.cancel(task_id):
        raise HTTPException(status_code=404, detail="no cancellable task")
    return {"cancelled": True}
