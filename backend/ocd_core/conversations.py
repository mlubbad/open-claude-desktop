"""Per-project conversations (Claude-style threads), persisted in Postgres (Phase 2).

Same public API + return shapes as the prior file-based module; only storage
changed. Datetimes are returned as ISO strings. The on-read legacy fold
(migrate_legacy_chat_history) is gone — handled once by ocd_core.db.migrate.
"""
from __future__ import annotations

import uuid

from sqlmodel import select

from . import config, util
from .db.engine import session
from .db.models import Conversation, utcnow


def _conv_title_from(text: str) -> str:
    t = " ".join((text or "").split())
    return (t[:48] + "…") if len(t) > 48 else (t or "New conversation")


def _to_dict(c: Conversation) -> dict:
    return {"id": c.id, "title": c.title,
            "created_at": c.created_at.isoformat(),
            "updated_at": c.updated_at.isoformat(),
            "pinned": c.pinned, "messages": list(c.transcript)}


def _summary(c: Conversation, project_id: str) -> dict:
    ts = c.updated_at.isoformat()
    return {"id": c.id, "title": c.title, "updated_at": ts,
            "updated_rel": util.relative_time(ts), "pinned": bool(c.pinned),
            "href": f"/project/{project_id}/c/{c.id}"}


def create_conversation(project_id: str, first_message: str) -> dict:
    now = utcnow()
    c = Conversation(id=uuid.uuid4().hex[:12], project_id=project_id,
                     title=_conv_title_from(first_message), pinned=False,
                     transcript=[{"role": "user", "content": first_message, "kind": "user"}],
                     created_at=now, updated_at=now)
    with session() as s:
        s.add(c)
        return _to_dict(c)


def get_conversation(project_id: str, conv_id: str) -> dict | None:
    with session() as s:
        c = s.get(Conversation, conv_id)
        return _to_dict(c) if c and c.project_id == project_id else None


def save_conversation(project_id: str, conv_id: str, messages: list[dict],
                      title: str | None = None) -> dict:
    with session() as s:
        c = s.get(Conversation, conv_id)
        if c is None or c.project_id != project_id:
            now = utcnow()
            c = Conversation(id=conv_id, project_id=project_id,
                             title=title or "Conversation", pinned=False,
                             transcript=[], created_at=now, updated_at=now)
        c.transcript = list(messages)[-config.CONV_MAX_MESSAGES:]
        if title:
            c.title = title
        c.updated_at = utcnow()
        s.add(c)
        return _to_dict(c)


def set_conversation_title(project_id: str, conv_id: str, title: str):
    with session() as s:
        c = s.get(Conversation, conv_id)
        if c and c.project_id == project_id:
            c.title = title
            c.updated_at = utcnow()
            s.add(c)


def set_conversation_pinned(project_id: str, conv_id: str, pinned: bool):
    with session() as s:
        c = s.get(Conversation, conv_id)
        if c and c.project_id == project_id:
            c.pinned = bool(pinned)
            s.add(c)


def move_conversation(src_pid: str, conv_id: str, dst_pid: str) -> bool:
    """Move a conversation from one project (or General) to another."""
    if src_pid == dst_pid:
        return True
    with session() as s:
        c = s.get(Conversation, conv_id)
        if not c or c.project_id != src_pid:
            return False
        c.project_id = dst_pid
        s.add(c)
        return True


def delete_conversation(project_id: str, conv_id: str):
    with session() as s:
        c = s.get(Conversation, conv_id)
        if c and c.project_id == project_id:
            s.delete(c)


def list_conversations(project_id: str) -> list[dict]:
    """Conversation summaries for the workspace 'Recents' list, newest first."""
    with session() as s:
        rows = s.exec(select(Conversation).where(Conversation.project_id == project_id)).all()
        out = [_summary(c, project_id) for c in rows]
    out.sort(key=lambda x: (x["pinned"], x["updated_at"]), reverse=True)
    return out


def list_all_conversations(limit: int = 200) -> list[dict]:
    """All conversations across every project, newest first.

    Feeds the global sidebar 'Recents' and the Chats dashboard. Each item adds
    project_id / project_name to the per-project summary shape.
    """
    from .projects import list_projects
    spaces = [(p["id"], p.get("name", "Untitled")) for p in list_projects()]
    spaces.append((config.GENERAL_ID, config.GENERAL_NAME))  # include non-project chats
    out = []
    for pid, pname in spaces:
        for c in list_conversations(pid):
            out.append({**c, "project_id": pid, "project_name": pname})
    out.sort(key=lambda x: (x["pinned"], x["updated_at"]), reverse=True)
    return out[:limit]


def generate_conversation_title(first_message: str) -> str:
    """Short Claude-style title from the first message (best-effort LLM, cheap)."""
    from .llm import get_llm_client
    try:
        llm = get_llm_client()
        resp = llm.chat.completions.create(
            model=config.FLASH_MODEL, temperature=0.2, max_tokens=20,
            messages=[{"role": "user", "content":
                       "Summarize this request as a 3-6 word title. No quotes, no "
                       f"trailing punctuation:\n\n{first_message}"}])
        t = (resp.choices[0].message.content or "").strip().strip('"').strip()
        t = t.split("\n")[0][:60]
        return t or _conv_title_from(first_message)
    except Exception:
        return _conv_title_from(first_message)
