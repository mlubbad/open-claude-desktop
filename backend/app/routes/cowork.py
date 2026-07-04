"""Cowork routes — delegate a task the agent runs autonomously in the background, then
list / inspect / cancel those tasks. Background tasks run with permission_mode=auto
(no human to answer HITL prompts)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from ocd_core import agent, cowork
from pydantic import BaseModel

from ..deps import current_user

router = APIRouter()


class CoworkStart(BaseModel):
    goal: str
    model: str
    provider: str | None = None
    effort: str = "High"
    project_id: str | None = None


@router.post("/cowork")
async def start_task(body: CoworkStart, user: str = Depends(current_user)) -> dict:
    """Delegate a goal to a background agent task. Returns the task summary immediately."""
    if not body.goal.strip():
        raise HTTPException(status_code=400, detail="goal is required")

    def gen_factory():
        # A fresh run_turn generator per launch; tools run without prompting (auto), and
        # web/artifact tools are enabled so the delegated work is autonomous. Subagents are
        # on so a big background task can fan work out into isolated, self-contained subtasks.
        return agent.run_turn(
            body.goal, [], body.project_id, body.model,
            effort=body.effort, provider=body.provider, permission_mode="auto",
            web_search=True, web_fetch=True, artifacts=True, memory=True, subagents=True,
        )

    task = cowork.manager.start(body.goal, gen_factory)
    return task.summary()


@router.get("/cowork")
def list_tasks(user: str = Depends(current_user)) -> list[dict]:
    return cowork.manager.list()


@router.get("/cowork/{task_id}")
def get_task(task_id: str, user: str = Depends(current_user)) -> dict:
    detail = cowork.manager.get(task_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="no such task")
    return detail


@router.post("/cowork/{task_id}/cancel")
def cancel_task(task_id: str, user: str = Depends(current_user)) -> dict:
    return {"cancelled": cowork.manager.cancel(task_id)}
