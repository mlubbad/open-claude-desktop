"""Per-project conversations (Claude-style threads), persisted in Postgres (Phase 2).

Same public API + return shapes as the prior file-based module; only storage
changed. Datetimes are returned as ISO strings. The on-read legacy fold
(migrate_legacy_chat_history) is gone — handled once by ocd_core.db.migrate.
"""
from __future__ import annotations

import json
import uuid

from sqlmodel import select

from . import config, tenancy, util
from .db.engine import session
from .db.models import Conversation, utcnow


class ConversationConflict(Exception):
    """A save was attempted against a stale version — another writer got there first.
    Carries the CURRENT server version so the caller can refetch and reconcile."""
    def __init__(self, current_version: int):
        self.current_version = current_version
        super().__init__(f"stale write (current version is {current_version})")


def _conv_title_from(text: str) -> str:
    t = " ".join((text or "").split())
    return (t[:48] + "…") if len(t) > 48 else (t or "New conversation")


def _to_dict(c: Conversation) -> dict:
    return {"id": c.id, "title": c.title,
            "created_at": c.created_at.isoformat(),
            "updated_at": c.updated_at.isoformat(),
            "pinned": c.pinned, "messages": list(c.transcript),
            "parent_id": c.parent_id, "fork_index": c.fork_index,
            "version": c.version}


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
    tenancy.stamp(c)  # tag with the current workspace when multi-tenancy is enforced
    with session() as s:
        s.add(c)
        return _to_dict(c)


def get_conversation(project_id: str, conv_id: str) -> dict | None:
    with session() as s:
        c = s.get(Conversation, conv_id)
        if c and c.project_id == project_id and tenancy.owns(c.workspace_id):
            return _to_dict(c)
        return None


def save_conversation(project_id: str, conv_id: str, messages: list[dict],
                      title: str | None = None, expected_version: int | None = None) -> dict:
    """Persist a conversation's transcript. When `expected_version` is given, the save is
    rejected with ConversationConflict if the stored row has already moved past it —
    another window/client wrote in between — so a stale client can't silently overwrite a
    newer transcript. On success the row's version is bumped and returned."""
    with session() as s:
        c = s.get(Conversation, conv_id)
        if c is None or c.project_id != project_id:
            now = utcnow()
            c = Conversation(id=conv_id, project_id=project_id,
                             title=title or "Conversation", pinned=False,
                             transcript=[], version=1, created_at=now, updated_at=now)
            tenancy.stamp(c)  # new row → tag with the current workspace when enforcing
        else:
            # Upsert can't degrade to a not-found create (the id already exists), so a
            # cross-workspace hit is denied outright rather than silently overwritten.
            tenancy.require_owned(c.workspace_id)
            if expected_version is not None and (c.version or 1) != expected_version:
                raise ConversationConflict(c.version or 1)
            c.version = (c.version or 1) + 1
        c.transcript = list(messages)[-config.CONV_MAX_MESSAGES:]
        if title:
            c.title = title
        c.updated_at = utcnow()
        s.add(c)
        return _to_dict(c)


def set_conversation_title(project_id: str, conv_id: str, title: str):
    with session() as s:
        c = s.get(Conversation, conv_id)
        if c and c.project_id == project_id and tenancy.owns(c.workspace_id):
            c.title = title
            c.updated_at = utcnow()
            s.add(c)


def set_conversation_pinned(project_id: str, conv_id: str, pinned: bool):
    with session() as s:
        c = s.get(Conversation, conv_id)
        if c and c.project_id == project_id and tenancy.owns(c.workspace_id):
            c.pinned = bool(pinned)
            s.add(c)


def move_conversation(src_pid: str, conv_id: str, dst_pid: str) -> bool:
    """Move a conversation from one project (or General) to another."""
    if src_pid == dst_pid:
        return True
    with session() as s:
        c = s.get(Conversation, conv_id)
        if not c or c.project_id != src_pid or not tenancy.owns(c.workspace_id):
            return False
        c.project_id = dst_pid
        s.add(c)
        return True


def delete_conversation(project_id: str, conv_id: str):
    with session() as s:
        c = s.get(Conversation, conv_id)
        if c and c.project_id == project_id and tenancy.owns(c.workspace_id):
            s.delete(c)


# --------------------------------------------------------------------------- #
#  Branching — fork a conversation at a message to explore an alternative path.
#  A branch is a NEW conversation whose transcript is a copy of the source up to
#  (and including) the fork message; it records the source id + fork index so the
#  UI can present the family as a tree and switch between branches. This reuses the
#  flat-transcript model wholesale — no in-place message tree — so nothing in the
#  agent/persistence pipeline changes.
# --------------------------------------------------------------------------- #
def branch_conversation(project_id: str, conv_id: str, at_index: int) -> dict | None:
    """Fork `conv_id` at message `at_index`; return the new branch conversation.

    Returns None if the source is missing/mismatched or the index is out of range.
    The branch keeps messages [0 .. at_index] and starts life editable from there."""
    with session() as s:
        src = s.get(Conversation, conv_id)
        if src is None or src.project_id != project_id or not tenancy.owns(src.workspace_id):
            return None
        msgs = list(src.transcript)
        if not (0 <= at_index < len(msgs)):
            return None
        now = utcnow()
        import copy
        branch = Conversation(
            id=uuid.uuid4().hex[:12], project_id=project_id,
            title=src.title, pinned=False,
            # Deep-copy so later edits to the branch never mutate the parent's blocks.
            transcript=copy.deepcopy(msgs[: at_index + 1]),
            parent_id=conv_id, fork_index=at_index,
            created_at=now, updated_at=now)
        tenancy.stamp(branch)  # the fork inherits the current workspace
        s.add(branch)
        return _to_dict(branch)


def branch_family(project_id: str, conv_id: str) -> dict:
    """The whole branch tree `conv_id` belongs to: walk up to the root, then collect
    every descendant. Returns {root, current, nodes:[{id,title,parent_id,fork_index,
    updated_at}]} — enough for the UI to draw the tree and highlight the current one."""
    with session() as s:
        cur = s.get(Conversation, conv_id)
        if cur is None or cur.project_id != project_id or not tenancy.owns(cur.workspace_id):
            return {"root": None, "current": conv_id, "nodes": []}
        # Walk parent links up to the root (guard against a cycle with a seen-set).
        root = cur
        seen = {root.id}
        while root.parent_id:
            p = s.get(Conversation, root.parent_id)
            if p is None or p.id in seen:
                break
            root, _ = p, seen.add(p.id)
        # BFS down from the root over parent_id edges.
        nodes: list[Conversation] = []
        queue = [root.id]
        visited: set[str] = set()
        while queue:
            cid = queue.pop(0)
            if cid in visited:
                continue
            visited.add(cid)
            node = s.get(Conversation, cid)
            if node is None:
                continue
            nodes.append(node)
            kids = s.exec(select(Conversation.id).where(
                Conversation.parent_id == cid)).all()
            queue.extend(k for k in kids if k not in visited)
        out = [{"id": n.id, "title": n.title, "parent_id": n.parent_id,
                "fork_index": n.fork_index, "updated_at": n.updated_at.isoformat(),
                "project_id": n.project_id} for n in nodes]
        out.sort(key=lambda x: x["updated_at"])
        return {"root": root.id, "current": conv_id, "nodes": out}


def list_conversations(project_id: str) -> list[dict]:
    """Conversation summaries for the workspace 'Recents' list, newest first.

    Column-projected: only the summary columns are read, never the transcript
    blob (which can be up to CONV_MAX_MESSAGES messages per row)."""
    q = select(*_SUMMARY_COLS).where(Conversation.project_id == project_id)
    clause = tenancy.scope_clause(Conversation.workspace_id)
    if clause is not None:
        q = q.where(clause)
    with session() as s:
        rows = s.exec(q).all()
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
    q = select(*_SUMMARY_COLS)
    clause = tenancy.scope_clause(Conversation.workspace_id)
    if clause is not None:
        q = q.where(clause)
    with session() as s:
        rows = s.exec(q).all()
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


def count_all_conversations() -> int:
    """Total conversation rows via a COUNT(*) — for diagnostics/inventory. Never
    materializes rows or transcripts (the old `len(list_all_conversations(100000))`
    loaded up to 100k projected rows just to count them)."""
    from sqlalchemy import func
    q = select(func.count()).select_from(Conversation)
    clause = tenancy.scope_clause(Conversation.workspace_id)
    if clause is not None:
        q = q.where(clause)
    with session() as s:
        return int(s.exec(q).one())


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
    stmt = select(Conversation)
    clause = tenancy.scope_clause(Conversation.workspace_id)
    if clause is not None:
        stmt = stmt.where(clause)
    with session() as s:
        rows = s.exec(stmt).all()
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
