from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from ocd_core import (
    agent,
    commands,
    integrations,
    observability,
    opik_tracing,
    permissions,
    profile,
    projects,
    settings,
    skills,
)
from sse_starlette.sse import EventSourceResponse

from ..deps import current_user, require_workspace_role
from ..schemas import AgentTurnRequest, PermissionReply
from ..sse import format_event

router = APIRouter()


@router.post("/agent/turn")
async def agent_turn(req: AgentTurnRequest, user: str = Depends(current_user)):
    if not observability.check_rate_limit(user):
        observability.audit({"event": "rate_limited", "user": user, "goal": req.goal[:200]})
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate limit exceeded")

    # Scan the skills dir ONCE and reuse it for both resolution and instruction
    # lookup (previously this parsed every skill file 2-3x per turn).
    available_skills = skills.list_skills()
    goal, skill_name, _ = commands.resolve_skill(req.goal, skills_list=available_skills)
    skill_instr = ((skills.get_skill(skill_name, skills_list=available_skills) or {})
                   .get("instructions", "") if skill_name else "")
    proj_instr = projects.get_project_instructions(req.project_id) if req.project_id else ""
    # Project memory is durable per-project context the user (or the agent) saved —
    # stored for a while, but never fed to the model until now (parity P0-4).
    proj_mem = projects.get_project_memory(req.project_id)[0] if req.project_id else ""
    extra_tools = integrations.agent_tools(req.enabled_plugins, req.enabled_connectors, req.enabled_mcp)
    observability.audit({"event": "agent_turn", "user": user,
                         "project": req.project_id, "goal": goal[:200]})

    o = req.options
    history = [m.model_dump() for m in req.history]
    turn_id = uuid.uuid4().hex
    user_profile = profile.render(settings.get_settings().get("profile") or {})

    async def stream():
        # First frame carries the turn_id so the client can reply to permission prompts
        # (and, later, cancel the turn).
        yield format_event({"type": "turn_start", "turn_id": turn_id})
        try:
            # Opik observability (opt-in) taps the event stream without touching it —
            # a no-op pass-through unless opik_enabled is on and the SDK is installed.
            turn = agent.run_turn(
                    goal, history, req.project_id, req.model, proj_instr,
                    effort=req.effort, web_search=o.web_search, skill_instructions=skill_instr,
                    research=o.research, extra_tools=extra_tools, web_fetch=o.web_fetch,
                    code_exec=o.code_exec, bash=o.bash, text_editor=o.text_editor, memory=o.memory,
                    provider=req.provider, turn_id=turn_id, permission_mode=req.permission_mode,
                    artifacts=o.artifacts, user_profile=user_profile, subagents=o.subagents,
                    project_memory=proj_mem, images=req.images, style=req.style or "")
            async for ev in opik_tracing.traced(
                    turn, goal=goal, model=req.model, provider=req.provider,
                    effort=req.effort, turn_id=turn_id, tags=["chat"]):
                yield format_event(ev)
        except Exception as e:
            yield format_event({"type": "error", "text": str(e)})
        yield format_event({"type": "done"})

    return EventSourceResponse(stream())


@router.post("/agent/turn/{turn_id}/permission")
async def agent_turn_permission(turn_id: str, reply: PermissionReply,
                                user: str = Depends(require_workspace_role("member"))) -> dict:
    """Resolve a pending `approval_required` prompt for a running turn."""
    if reply.decision not in ("approve", "decline"):
        raise HTTPException(422, "decision must be 'approve' or 'decline'")
    resolved = permissions.registry.resolve(
        turn_id, reply.tool_call_id, reply.decision == "approve")
    if not resolved:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "no pending approval for this turn/tool_call_id")
    observability.audit({"event": "tool_permission", "user": user, "turn": turn_id,
                         "tool_call_id": reply.tool_call_id, "decision": reply.decision})
    return {"resolved": True, "decision": reply.decision}
