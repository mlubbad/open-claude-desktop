"""Per-project conversations (Claude-style threads), persisted in Postgres (Phase 2).

Same public API + return shapes as the prior file-based module; only storage
changed. Datetimes are returned as ISO strings. The on-read legacy fold
(migrate_legacy_chat_history) is gone — handled once by ocd_core.db.migrate.
"""
from __future__ import annotations

import json
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


def _summary_fields(cid: str, title: str, updated_at, pinned, project_id: str) -> dict:
    """The 'Recents' summary shape from raw columns (no transcript needed)."""
    ts = updated_at.isoformat()
    return {"id": cid, "title": title, "updated_at": ts,
            "updated_rel": util.relative_time(ts), "pinned": bool(pinned),
            "href": f"/project/{project_id}/c/{cid}"}


def _summary(c: Conversation, project_id: str) -> dict:
    return _summary_fields(c.id, c.title, c.updated_at, c.pinned, project_id)


# Summary columns only — deliberately EXCLUDES the transcript JSON blob so a
# listing never drags every conversation's full message history off disk.
_SUMMARY_COLS = (Conversation.id, Conversation.title, Conversation.updated_at,
                 Conversation.pinned, Conversation.project_id)


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
    """Conversation summaries for the workspace 'Recents' list, newest first.

    Column-projected: only the summary columns are read, never the transcript
    blob (which can be up to CONV_MAX_MESSAGES messages per row)."""
    with session() as s:
        rows = s.exec(select(*_SUMMARY_COLS)
                      .where(Conversation.project_id == project_id)).all()
    out = [_summary_fields(cid, title, updated_at, pinned, project_id)
           for (cid, title, updated_at, pinned, _pid) in rows]
    out.sort(key=lambda x: (x["pinned"], x["updated_at"]), reverse=True)
    return out


def list_all_conversations(limit: int = 200) -> list[dict]:
    """All conversations across every project, newest first.

    Feeds the global sidebar 'Recents' and the Chats dashboard. Each item adds
    project_id / project_name to the per-project summary shape.

    ONE column-projected query over every conversation plus one projects lookup —
    not a per-project query loop (the old N+1) and not a transcript load per row.
    Conversations whose project no longer exists are skipped, matching the prior
    project-by-project behaviour.
    """
    from .projects import list_projects
    names = {p["id"]: p.get("name", "Untitled") for p in list_projects()}
    names[config.GENERAL_ID] = config.GENERAL_NAME  # non-project chats
    with session() as s:
        rows = s.exec(select(*_SUMMARY_COLS)).all()
    out = []
    for (cid, title, updated_at, pinned, pid) in rows:
        if pid not in names:
            continue  # orphaned (project deleted) — not shown, as before
        item = _summary_fields(cid, title, updated_at, pinned, pid)
        item["project_id"] = pid
        item["project_name"] = names[pid]
        out.append(item)
    out.sort(key=lambda x: (x["pinned"], x["updated_at"]), reverse=True)
    return out[:limit]


# --------------------------------------------------------------------------- #
#  Full-text search across every conversation (title + message bodies).
#
#  Portable in-Python scan (works identically on SQLite and Postgres) — the desktop
#  scale (hundreds of threads, each capped at CONV_MAX_MESSAGES) makes an FTS index
#  unnecessary. Assistant turns are stored as JSON block lists (see the desktop
#  persist layer), so we extract the human-readable text before matching.
# --------------------------------------------------------------------------- #
def _message_text(m: dict) -> str:
    """Human-readable text of one stored message. For assistant 'blocks' turns,
    pull the answer/thinking text, tool summaries, and artifact titles/content."""
    content = m.get("content", "")
    if m.get("kind") != "blocks":
        return content if isinstance(content, str) else ""
    try:
        blocks = json.loads(content)
    except (ValueError, TypeError):
        return content if isinstance(content, str) else ""
    parts: list[str] = []
    for b in blocks if isinstance(blocks, list) else []:
        if not isinstance(b, dict):
            continue
        bk = b.get("kind")
        if bk in ("answer", "thinking"):
            parts.append(str(b.get("text", "")))
        elif bk == "tool":
            parts.append(str(b.get("summary", "")))
        elif bk == "artifact":
            doc = b.get("doc", {}) or {}
            parts.append(str(doc.get("title", "")))
            parts.append(str(doc.get("content", "")))
    return "\n".join(p for p in parts if p)


def _snippet(text: str, idx: int, qlen: int, radius: int = 40) -> str:
    """A one-line context window around a match, with ellipses and collapsed space."""
    start = max(0, idx - radius)
    end = min(len(text), idx + qlen + radius)
    s = " ".join(text[start:end].split())
    if start > 0:
        s = "…" + s
    if end < len(text):
        s = s + "…"
    return s


def _match_conversation(c: Conversation, ql: str, qlen: int) -> tuple[str, str] | None:
    """Return (matched_in, snippet) for the first title/message hit, else None."""
    if ql in (c.title or "").lower():
        return "title", c.title or ""
    for m in c.transcript:
        if not isinstance(m, dict):
            continue
        text = _message_text(m)
        i = text.lower().find(ql)
        if i != -1:
            return str(m.get("role", "")), _snippet(text, i, qlen)
    return None


def search_conversations(query: str, limit: int = 50) -> list[dict]:
    """Conversations whose title or any message contains ``query`` (case-insensitive),
    newest/pinned first. Each result is a summary plus ``snippet`` and ``matched_in``."""
    q = (query or "").strip()
    if not q:
        return []
    ql = q.lower()
    from .projects import list_projects
    names = {p["id"]: p.get("name", "Untitled") for p in list_projects()}
    names[config.GENERAL_ID] = config.GENERAL_NAME
    out: list[dict] = []
    with session() as s:
        rows = s.exec(select(Conversation)).all()
        rows = sorted(rows, key=lambda c: (c.pinned, c.updated_at), reverse=True)
        for c in rows:
            hit = _match_conversation(c, ql, len(q))
            if hit is None:
                continue
            out.append({**_summary(c, c.project_id), "project_id": c.project_id,
                        "project_name": names.get(c.project_id, "Untitled"),
                        "matched_in": hit[0], "snippet": hit[1]})
            if len(out) >= limit:
                break
    return out


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
