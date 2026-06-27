"""Project registry + per-project metadata (instructions, memory, allowlist).

Moved verbatim from aj360_app/aj360_app/core.py — identical semantics to the
original app.py. Behavior parity is the contract; only import references were
adjusted (util.slugify for the old _slugify, ocd_core.chroma for _get_chroma).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from . import config, util
from .chroma import _get_chroma

# Match core.py: ensure the projects dir exists and snapshot the registry path.
config.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
_REGISTRY_FILE = config.PROJECTS_DIR / "_registry.json"


def get_project_allowlist(project_id: str) -> list:
    """Optional per-project table allowlist (projects/<id>/allowlist.json)."""
    path = config.PROJECTS_DIR / project_id / "allowlist.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


# --------------------------------------------------------------------------- #
#  Projects registry (identical semantics to app.py)
# --------------------------------------------------------------------------- #
def _load_registry() -> list[dict]:
    if _REGISTRY_FILE.exists():
        try:
            return json.loads(_REGISTRY_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
    return []


def _save_registry(data: list[dict]):
    tmp = _REGISTRY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(_REGISTRY_FILE)


def list_projects() -> list[dict]:
    return _load_registry()


def get_project(project_id: str) -> dict | None:
    return next((p for p in _load_registry() if p["id"] == project_id), None)


def create_project(name: str) -> dict:
    projects = _load_registry()
    project_id = util.slugify(name)
    if project_id in {p["id"] for p in projects}:
        project_id = f"{project_id}-{uuid.uuid4().hex[:4]}"

    (config.PROJECTS_DIR / project_id / "knowledge").mkdir(parents=True, exist_ok=True)
    instructions_path = config.PROJECTS_DIR / project_id / "instructions.md"
    if not instructions_path.exists():
        instructions_path.write_text(
            f"# Instructions for {name}\n\nAdd specific guidelines for this project here.\n",
            encoding="utf-8")

    meta = {"id": project_id, "name": name,
            "created_at": datetime.now(timezone.utc).isoformat()}
    projects.append(meta)
    _save_registry(projects)
    return meta


def delete_project(project_id: str) -> bool:
    projects = _load_registry()
    updated = [p for p in projects if p["id"] != project_id]
    if len(updated) == len(projects):
        return False
    _save_registry(updated)
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
    path = config.PROJECTS_DIR / project_id / "instructions.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def save_project_instructions(project_id: str, content: str):
    path = config.PROJECTS_DIR / project_id / "instructions.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def get_project_memory(project_id: str) -> tuple[str, str]:
    """Returns (memory_text, last_updated_relative) from optional memory.md."""
    path = config.PROJECTS_DIR / project_id / "memory.md"
    if path.exists():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
            return text, util.relative_time(path.stat().st_mtime)
        except Exception:
            return "", ""
    return "", ""


def save_project_memory(project_id: str, content: str):
    path = config.PROJECTS_DIR / project_id / "memory.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# --------------------------------------------------------------------------- #
#  Files / capacity (project-scoped)
# --------------------------------------------------------------------------- #
def project_capacity(project_id: str) -> dict:
    # Imported lazily to avoid a knowledge<->projects import cycle; knowledge
    # imports projects only via list_project_files at call time below.
    from .knowledge import list_project_files
    files = list_project_files(project_id)
    used = sum(f["size"] for f in files)
    pct = min(int(used / config.PROJECT_CAPACITY_BYTES * 100), 100) \
        if config.PROJECT_CAPACITY_BYTES else 0
    return {"used_mb": round(used / (1024 * 1024), 1),
            "max_mb": round(config.PROJECT_CAPACITY_BYTES / (1024 * 1024), 1),
            "percent": pct}


# --------------------------------------------------------------------------- #
#  Display helpers
# --------------------------------------------------------------------------- #
def project_card_view(p: dict) -> dict:
    """Shape a registry entry for the dashboard card."""
    instr = get_project_instructions(p["id"])
    desc = instr.split("\n")[0].replace("#", "").strip()
    if not desc or len(desc) < 5:
        desc = "No description provided yet."
    if len(desc) > 80:
        desc = desc[:77] + "…"
    return {"id": p["id"], "name": p.get("name", "Untitled"),
            "updated": util.format_date(p.get("created_at", "")), "desc": desc,
            "href": f"/project/{p['id']}"}
