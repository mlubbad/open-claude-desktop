"""Per-project CONVERSATIONS (Claude-style threads).

Moved verbatim from aj360_app/aj360_app/core.py. Each conversation is
projects/<id>/conversations/<cid>.json:
  {id, title, created_at, updated_at, messages: [{role, content, kind}, ...]}
Behavior parity is the contract; only import references were adjusted
(config.* for module constants, util.relative_time, llm.get_llm_client,
projects.list_projects for the cross-project aggregate).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import config, util


def _conv_dir(project_id: str) -> Path:
    return config.PROJECTS_DIR / project_id / "conversations"


def _conv_path(project_id: str, conv_id: str) -> Path:
    return _conv_dir(project_id) / f"{conv_id}.json"


def _conv_title_from(text: str) -> str:
    t = " ".join((text or "").split())
    return (t[:48] + "…") if len(t) > 48 else (t or "New conversation")


def _write_conversation(project_id: str, conv: dict):
    d = _conv_dir(project_id)
    d.mkdir(parents=True, exist_ok=True)
    path = _conv_path(project_id, conv["id"])
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(conv, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # atomic


def create_conversation(project_id: str, first_message: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    conv = {
        "id": uuid.uuid4().hex[:12],
        "title": _conv_title_from(first_message),
        "created_at": now, "updated_at": now,
        "messages": [{"role": "user", "content": first_message, "kind": "user"}],
    }
    _write_conversation(project_id, conv)
    return conv


def get_conversation(project_id: str, conv_id: str) -> dict | None:
    path = _conv_path(project_id, conv_id)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return None


def save_conversation(project_id: str, conv_id: str, messages: list[dict],
                      title: str | None = None) -> dict:
    conv = get_conversation(project_id, conv_id) or {
        "id": conv_id, "title": title or "Conversation",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    conv["messages"] = list(messages)[-config.CONV_MAX_MESSAGES:]
    if title:
        conv["title"] = title
    conv["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_conversation(project_id, conv)
    return conv


def set_conversation_title(project_id: str, conv_id: str, title: str):
    conv = get_conversation(project_id, conv_id)
    if conv:
        conv["title"] = title
        _write_conversation(project_id, conv)


def set_conversation_pinned(project_id: str, conv_id: str, pinned: bool):
    conv = get_conversation(project_id, conv_id)
    if conv:
        conv["pinned"] = bool(pinned)
        _write_conversation(project_id, conv)


def move_conversation(src_pid: str, conv_id: str, dst_pid: str) -> bool:
    """Move a conversation file from one project (or General) to another."""
    if src_pid == dst_pid:
        return True
    conv = get_conversation(src_pid, conv_id)
    if not conv:
        return False
    _write_conversation(dst_pid, conv)
    delete_conversation(src_pid, conv_id)
    return True


def delete_conversation(project_id: str, conv_id: str):
    try:
        _conv_path(project_id, conv_id).unlink()
    except Exception:
        pass


def list_conversations(project_id: str) -> list[dict]:
    """Conversation summaries for the workspace 'Recents' list, newest first."""
    migrate_legacy_chat_history(project_id)
    d = _conv_dir(project_id)
    out = []
    if d.exists():
        for f in d.glob("*.json"):
            try:
                c = json.loads(f.read_text(encoding="utf-8"))
                ts = c.get("updated_at") or c.get("created_at") or ""
                out.append({
                    "id": c["id"], "title": c.get("title", "Conversation"),
                    "updated_at": ts, "updated_rel": util.relative_time(ts) if ts else "recently",
                    "pinned": bool(c.get("pinned", False)),
                    "href": f"/project/{project_id}/c/{c['id']}",
                })
            except Exception:
                continue
    out.sort(key=lambda x: (x["pinned"], x["updated_at"]), reverse=True)
    return out


def list_all_conversations(limit: int = 200) -> list[dict]:
    """All conversations across every project, newest first.

    Feeds the global sidebar 'Recents' and the Chats dashboard. Each item adds
    project_id / project_name to the per-project summary shape.
    """
    from .projects import list_projects
    out = []
    spaces = [(p["id"], p.get("name", "Untitled")) for p in list_projects()]
    spaces.append((config.GENERAL_ID, config.GENERAL_NAME))  # include non-project chats
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


def migrate_legacy_chat_history(project_id: str):
    """One-time fold of the old single chat_history.json into a conversation."""
    legacy = config.PROJECTS_DIR / project_id / "chat_history.json"
    if not legacy.exists():
        return
    has_convs = _conv_dir(project_id).exists() and any(_conv_dir(project_id).glob("*.json"))
    if not has_convs:
        try:
            msgs = json.loads(legacy.read_text(encoding="utf-8"))
            if isinstance(msgs, list) and msgs:
                first = next((m.get("content", "") for m in msgs
                              if m.get("kind") == "user"), "Imported conversation")
                now = datetime.now(timezone.utc).isoformat()
                _write_conversation(project_id, {
                    "id": uuid.uuid4().hex[:12], "title": _conv_title_from(first),
                    "created_at": now, "updated_at": now, "messages": msgs})
        except Exception:
            pass
    try:
        legacy.unlink()
    except Exception:
        pass
