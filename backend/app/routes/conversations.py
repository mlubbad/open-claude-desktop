from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from ocd_core import conversations

from ..deps import current_user
from ..schemas import (
    BranchBody,
    ConversationCreate,
    ConversationPatch,
    ConversationSave,
    MoveBody,
    TitleRequest,
)

router = APIRouter()


@router.get("/projects/{pid}/conversations")
def list_convs(pid: str, user: str = Depends(current_user)) -> list[dict]:
    return conversations.list_conversations(pid)


@router.post("/projects/{pid}/conversations")
def create_conv(pid: str, body: ConversationCreate, user: str = Depends(current_user)) -> dict:
    return conversations.create_conversation(pid, body.first_message)


@router.get("/projects/{pid}/conversations/{cid}")
def get_conv(pid: str, cid: str, user: str = Depends(current_user)) -> dict:
    c = conversations.get_conversation(pid, cid)
    if not c:
        raise HTTPException(404, "not found")
    return c


@router.put("/projects/{pid}/conversations/{cid}")
def save_conv(pid: str, cid: str, body: ConversationSave, user: str = Depends(current_user)) -> dict:
    return conversations.save_conversation(pid, cid, [m.model_dump() for m in body.messages], body.title)


@router.patch("/projects/{pid}/conversations/{cid}")
def patch_conv(pid: str, cid: str, body: ConversationPatch, user: str = Depends(current_user)) -> dict:
    if body.title is not None:
        conversations.set_conversation_title(pid, cid, body.title)
    if body.pinned is not None:
        conversations.set_conversation_pinned(pid, cid, body.pinned)
    return {"ok": True}


@router.delete("/projects/{pid}/conversations/{cid}")
def delete_conv(pid: str, cid: str, user: str = Depends(current_user)) -> dict:
    conversations.delete_conversation(pid, cid)
    return {"ok": True}


@router.post("/projects/{pid}/conversations/{cid}/move")
def move_conv(pid: str, cid: str, body: MoveBody, user: str = Depends(current_user)) -> dict:
    return {"ok": conversations.move_conversation(pid, cid, body.dst_project_id)}


@router.post("/projects/{pid}/conversations/{cid}/branch")
def branch_conv(pid: str, cid: str, body: BranchBody, user: str = Depends(current_user)) -> dict:
    """Fork the conversation at a message; returns the new branch conversation."""
    branch = conversations.branch_conversation(pid, cid, body.at_index)
    if branch is None:
        raise HTTPException(404, "cannot branch: no such conversation or index out of range")
    return branch


@router.get("/projects/{pid}/conversations/{cid}/branches")
def conv_branches(pid: str, cid: str, user: str = Depends(current_user)) -> dict:
    """The branch family (tree) this conversation belongs to, for the switcher."""
    return conversations.branch_family(pid, cid)


@router.get("/conversations")
def list_all(limit: int = 200, user: str = Depends(current_user)) -> list[dict]:
    return conversations.list_all_conversations(limit)


@router.get("/conversations/search")
def search_convs(q: str, limit: int = 50, user: str = Depends(current_user)) -> list[dict]:
    """Full-text search across all conversations (title + message bodies)."""
    return conversations.search_conversations(q, limit)


@router.post("/conversations/title")
def conversation_title(body: TitleRequest, user: str = Depends(current_user)) -> dict:
    return {"title": conversations.generate_conversation_title(body.first_message)}
