"""Project registry + per-project metadata, persisted in Postgres (Phase 2).

Same public API and return shapes as the prior file-based module; only the
storage changed. Datetimes are returned as ISO strings. Uploaded KB files still
live on disk under projects/<id>/knowledge/ and ChromaDB still holds vectors.
"""
from __future__ import annotations

import uuid

from sqlmodel import select

from . import config, util
from .chroma import _get_chroma
from .db.engine import session
from .db.models import Project, utcnow

# Uploaded files still live on disk; ensure the root exists (parity with the old module).
config.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def _meta(p: Project) -> dict:
    return {"id": p.id, "name": p.name, "created_at": p.created_at.isoformat()}


def get_project_allowlist(project_id: str) -> list:
    with session() as s:
        p = s.get(Project, project_id)
        return list(p.allowlist) if p and p.allowlist else []


def list_projects() -> list[dict]:
    with session() as s:
        return [_meta(p) for p in s.exec(select(Project).order_by(Project.created_at)).all()]


def get_project(project_id: str) -> dict | None:
    with session() as s:
        p = s.get(Project, project_id)
        return _meta(p) if p else None


def create_project(name: str) -> dict:
    project_id = util.slugify(name)
    with session() as s:
        if s.get(Project, project_id) is not None:
            project_id = f"{project_id}-{uuid.uuid4().hex[:4]}"
        now = utcnow()
        p = Project(id=project_id, name=name,
                    instructions=f"# Instructions for {name}\n\n"
                                 "Add specific guidelines for this project here.\n",
                    memory="", allowlist=[], created_at=now, updated_at=now)
        s.add(p)
        meta = _meta(p)
    (config.PROJECTS_DIR / project_id / "knowledge").mkdir(parents=True, exist_ok=True)
    return meta


def delete_project(project_id: str) -> bool:
    with session() as s:
        p = s.get(Project, project_id)
        if p is None:
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
        return p.instructions if p else ""


def save_project_instructions(project_id: str, content: str):
    with session() as s:
        p = s.get(Project, project_id)
        if p:
            p.instructions = content
            p.updated_at = utcnow()
            s.add(p)


def get_project_memory(project_id: str) -> tuple[str, str]:
    """Returns (memory_text, last_updated_relative). Timestamp from updated_at."""
    with session() as s:
        p = s.get(Project, project_id)
        if not p:
            return "", ""
        return p.memory, (util.relative_time(p.updated_at.isoformat()) if p.memory else "")


def save_project_memory(project_id: str, content: str):
    with session() as s:
        p = s.get(Project, project_id)
        if p:
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
    instr = get_project_instructions(p["id"])
    desc = instr.split("\n")[0].replace("#", "").strip()
    if not desc or len(desc) < 5:
        desc = "No description provided yet."
    if len(desc) > 80:
        desc = desc[:77] + "…"
    return {"id": p["id"], "name": p.get("name", "Untitled"),
            "updated": util.format_date(p.get("created_at", "")), "desc": desc,
            "href": f"/project/{p['id']}"}
