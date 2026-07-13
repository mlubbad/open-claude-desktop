"""Project registry + per-project metadata, persisted in Postgres (Phase 2).

Same public API and return shapes as the prior file-based module; only the
storage changed. Datetimes are returned as ISO strings. Uploaded KB files still
live on disk under projects/<id>/knowledge/ and ChromaDB still holds vectors.
"""
from __future__ import annotations

import uuid

from sqlmodel import select

from . import config, tenancy, util
from .chroma import _get_chroma
from .db.engine import session
from .db.models import Project, utcnow

# Uploaded files still live on disk; ensure the root exists (parity with the old module).
config.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def _meta(p: Project) -> dict:
    """Full project card metadata for the Projects grid + sidebar."""
    return {"id": p.id, "name": p.name,
            "description": getattr(p, "description", "") or "",
            "pinned": bool(getattr(p, "pinned", False)),
            "archived": bool(getattr(p, "archived", False)),
            "created_at": p.created_at.isoformat(),
            "updated_at": p.updated_at.isoformat(),
            "updated_rel": util.relative_time(p.updated_at.isoformat())}


def get_project_allowlist(project_id: str) -> list:
    with session() as s:
        p = s.get(Project, project_id)
        if not (p and tenancy.owns(p.workspace_id)):
            return []
        return list(p.allowlist) if p.allowlist else []


def save_project_allowlist(project_id: str, tables: list) -> bool:
    """Persist the dataset/table allowlist on the Project row."""
    with session() as s:
        p = s.get(Project, project_id)
        if p is None or not tenancy.owns(p.workspace_id):
            return False
        p.allowlist = list(tables)
        p.updated_at = utcnow()
        s.add(p)
        return True


def list_projects(include_archived: bool = False) -> list[dict]:
    """All projects (newest-updated first). Archived projects are excluded unless asked.
    Scoped to the current workspace when multi-tenancy is enforced."""
    with session() as s:
        q = select(Project)
        if not include_archived:
            # getattr default keeps this working before the column-ensure migration runs.
            q = q.where((Project.archived == False) | (Project.archived == None))  # noqa: E711,E712
        clause = tenancy.scope_clause(Project.workspace_id)
        if clause is not None:
            q = q.where(clause)
        rows = s.exec(q).all()
    rows.sort(key=lambda p: p.updated_at, reverse=True)
    return [_meta(p) for p in rows]


def get_project(project_id: str) -> dict | None:
    with session() as s:
        p = s.get(Project, project_id)
        return _meta(p) if p and tenancy.owns(p.workspace_id) else None


def create_project(name: str, description: str = "") -> dict:
    project_id = util.slugify(name)
    desc = (description or "").strip()
    # Seed the project instructions from the stated goal so chats are grounded from the
    # start (the agent reads instructions, not the card description). The user can refine
    # them later via "Set instructions". Empty goal -> the editable placeholder.
    instructions = (f"# {name}\n\n{desc}\n" if desc
                    else f"# Instructions for {name}\n\n"
                         "Add specific guidelines for this project here.\n")
    with session() as s:
        if s.get(Project, project_id) is not None:
            project_id = f"{project_id}-{uuid.uuid4().hex[:4]}"
        now = utcnow()
        p = Project(id=project_id, name=name, description=desc, instructions=instructions,
                    memory="", allowlist=[], created_at=now, updated_at=now)
        tenancy.stamp(p)  # tag with the current workspace when multi-tenancy is enforced
        s.add(p)
        meta = _meta(p)
    (config.PROJECTS_DIR / project_id / "knowledge").mkdir(parents=True, exist_ok=True)
    return meta


def update_project(project_id: str, *, name: str | None = None,
                   description: str | None = None, pinned: bool | None = None,
                   archived: bool | None = None) -> dict | None:
    """Patch a project's card fields (name/description) or state (pinned/archived).
    Only provided fields change. Returns the updated metadata, or None if not found."""
    with session() as s:
        p = s.get(Project, project_id)
        if p is None or not tenancy.owns(p.workspace_id):
            return None
        if name is not None and name.strip():
            p.name = name.strip()
        if description is not None:
            p.description = description.strip()
        if pinned is not None:
            p.pinned = bool(pinned)
        if archived is not None:
            p.archived = bool(archived)
        p.updated_at = utcnow()
        s.add(p)
        return _meta(p)


def delete_project(project_id: str) -> bool:
    with session() as s:
        p = s.get(Project, project_id)
        if p is None or not tenancy.owns(p.workspace_id):
            return False
        s.delete(p)
        from .db.models import Conversation
        for c in s.exec(select(Conversation).where(Conversation.project_id == project_id)).all():
            s.delete(c)
    proj_dir = config.PROJECTS_DIR / project_id
    if proj_dir.exists():
        import shutil
        shutil.rmtree(proj_dir, ignore_errors=True)
    try:
        _get_chroma().delete_collection(f"kb_project_{project_id}")
    except Exception:
        pass
    return True


def get_project_instructions(project_id: str) -> str:
    with session() as s:
        p = s.get(Project, project_id)
        return p.instructions if p and tenancy.owns(p.workspace_id) else ""


def save_project_instructions(project_id: str, content: str):
    with session() as s:
        p = s.get(Project, project_id)
        if p and tenancy.owns(p.workspace_id):
            p.instructions = content
            p.updated_at = utcnow()
            s.add(p)


def get_project_memory(project_id: str) -> tuple[str, str]:
    """Returns (memory_text, last_updated_relative). Timestamp from updated_at."""
    with session() as s:
        p = s.get(Project, project_id)
        if not (p and tenancy.owns(p.workspace_id)):
            return "", ""
        return p.memory, (util.relative_time(p.updated_at.isoformat()) if p.memory else "")


def save_project_memory(project_id: str, content: str):
    with session() as s:
        p = s.get(Project, project_id)
        if p and tenancy.owns(p.workspace_id):
            p.memory = content
            p.updated_at = utcnow()
            s.add(p)


def project_capacity(project_id: str) -> dict:
    # Unchanged: uploaded files still live on disk.
    from .knowledge import list_project_files
    files = list_project_files(project_id)
    used = sum(f["size"] for f in files)
    pct = min(int(used / config.PROJECT_CAPACITY_BYTES * 100), 100) \
        if config.PROJECT_CAPACITY_BYTES else 0
    return {"used_mb": round(used / (1024 * 1024), 1),
            "max_mb": round(config.PROJECT_CAPACITY_BYTES / (1024 * 1024), 1),
            "percent": pct}


def project_card_view(p: dict) -> dict:
    desc = (p.get("description") or "").strip()
    if not desc:  # fall back to the first instructions line for older projects
        instr = get_project_instructions(p["id"])
        desc = instr.split("\n")[0].replace("#", "").strip()
    if not desc or len(desc) < 5:
        desc = "No description provided yet."
    if len(desc) > 80:
        desc = desc[:77] + "…"
    return {"id": p["id"], "name": p.get("name", "Untitled"),
            "updated": util.format_date(p.get("created_at", "")), "desc": desc,
            "href": f"/project/{p['id']}"}
