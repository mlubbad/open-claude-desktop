from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from ocd_core import agent, commands, integrations, observability, projects, skills
from sse_starlette.sse import EventSourceResponse

from ..deps import current_user
from ..schemas import AgentTurnRequest
from ..sse import format_event

router = APIRouter()


@router.post("/agent/turn")
async def agent_turn(req: AgentTurnRequest, user: str = Depends(current_user)):
    if not observability.check_rate_limit(user):
        observability.audit({"event": "rate_limited", "user": user, "goal": req.goal[:200]})
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate limit exceeded")

    goal, skill_name, _ = commands.resolve_skill(req.goal)
    skill_instr = (skills.get_skill(skill_name) or {}).get("instructions", "") if skill_name else ""
    proj_instr = projects.get_project_instructions(req.project_id) if req.project_id else ""
    extra_tools = integrations.agent_tools(req.enabled_plugins, req.enabled_connectors, req.enabled_mcp)
    observability.audit({"event": "agent_turn", "user": user,
                         "project": req.project_id, "goal": goal[:200]})

    o = req.options
    history = [m.model_dump() for m in req.history]

    async def stream():
        try:
            async for ev in agent.run_turn(
                    goal, history, req.project_id, req.model, proj_instr,
                    effort=req.effort, web_search=o.web_search, skill_instructions=skill_instr,
                    research=o.research, extra_tools=extra_tools, web_fetch=o.web_fetch,
                    code_exec=o.code_exec, bash=o.bash, text_editor=o.text_editor, memory=o.memory):
                yield format_event(ev)
        except Exception as e:
            yield format_event({"type": "error", "text": str(e)})
        yield format_event({"type": "done"})

    return EventSourceResponse(stream())
