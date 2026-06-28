"""One-time, idempotent filesystem → Postgres migration (Phase 2).

Reads the legacy projects/ tree (registry + per-project metadata files +
conversation JSONs, including the general/ bucket and any legacy
chat_history.json) and upserts Project/Conversation rows. Safe to re-run.

Run: python -m ocd_core.db.migrate   (uses DATABASE_URL + alembic head)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .engine import session
from .models import Conversation, Project, utcnow


def _parse_dt(value: str | None) -> datetime:
    if value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return utcnow()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def migrate_filesystem_to_db(projects_dir) -> dict:
    """Upsert all projects + conversations from the file tree. Returns counts."""
    projects_dir = Path(projects_dir)
    n_projects = n_convs = 0

    registry = _read_json(projects_dir / "_registry.json", [])
    with session() as s:
        for entry in registry:
            pid = entry["id"]
            pdir = projects_dir / pid
            p = s.get(Project, pid) or Project(id=pid, name=entry.get("name", pid))
            p.name = entry.get("name", pid)
            p.instructions = _read_text(pdir / "instructions.md")
            p.memory = _read_text(pdir / "memory.md")
            p.allowlist = _read_json(pdir / "allowlist.json", [])
            p.created_at = _parse_dt(entry.get("created_at"))
            p.updated_at = p.created_at
            s.add(p)
            n_projects += 1

    conv_dirs = [d for d in projects_dir.iterdir()
                 if d.is_dir() and (d / "conversations").is_dir()] if projects_dir.exists() else []
    with session() as s:
        for pdir in conv_dirs:
            pid = pdir.name
            legacy = pdir / "chat_history.json"
            if legacy.exists():
                msgs = _read_json(legacy, [])
                if isinstance(msgs, list) and msgs:
                    first = next((m.get("content", "") for m in msgs
                                  if m.get("kind") == "user"), "Imported conversation")
                    cid = f"legacy-{pid}"  # deterministic → idempotent across re-runs
                    c = s.get(Conversation, cid) or Conversation(
                        id=cid, project_id=pid, title="", created_at=utcnow())
                    c.project_id = pid
                    c.title = (first[:48] or "Imported")
                    c.transcript = msgs
                    c.updated_at = utcnow()
                    s.add(c)
                    n_convs += 1
            for cf in (pdir / "conversations").glob("*.json"):
                data = _read_json(cf, None)
                if not isinstance(data, dict) or "id" not in data:
                    continue
                cid = data["id"]
                c = s.get(Conversation, cid) or Conversation(id=cid, project_id=pid, title="")
                c.project_id = pid
                c.title = data.get("title", "Conversation")
                c.pinned = bool(data.get("pinned", False))
                c.transcript = data.get("messages", [])
                c.created_at = _parse_dt(data.get("created_at"))
                c.updated_at = _parse_dt(data.get("updated_at") or data.get("created_at"))
                s.add(c)
                n_convs += 1

    return {"projects": n_projects, "conversations": n_convs}


def _main() -> int:
    import shutil
    from ocd_core.config import PROJECTS_DIR  # only here, to avoid eager config reads
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = PROJECTS_DIR.parent / f"projects.backup-{stamp}"
    if PROJECTS_DIR.exists():
        shutil.copytree(PROJECTS_DIR, backup)
        print(f"[migrate] backed up {PROJECTS_DIR} -> {backup}")
    import subprocess
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd="backend", check=True)
    counts = migrate_filesystem_to_db(PROJECTS_DIR)
    print(f"[migrate] migrated {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
