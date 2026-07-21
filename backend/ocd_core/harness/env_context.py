# backend/ocd_core/harness/env_context.py
"""Environment section appended to the system prompt for workspace turns: platform,
workspace root, git state, and a bounded file map. Deterministic and git-optional
(never fails the turn if git is missing)."""
from __future__ import annotations

import platform
import subprocess
from pathlib import Path

_IGNORE = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
           ".next", "target", ".mypy_cache", ".pytest_cache", ".ruff_cache"}


def _git(root: Path, *args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True,
                             text=True, errors="replace", timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""


def _file_map(root: Path, max_entries: int) -> list[str]:
    entries: list[str] = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(part in _IGNORE for part in rel.parts):
            continue
        if len(rel.parts) > 2:   # depth-2 cap
            continue
        entries.append(rel.as_posix() + ("/" if p.is_dir() else ""))
        if len(entries) >= max_entries:
            entries.append("… (truncated)")
            break
    return entries


def build(workspace_root, max_entries: int = 200) -> str:
    root = Path(workspace_root)
    lines = ["# WORKSPACE ENVIRONMENT",
             f"Working directory: {root}",
             f"Platform: {platform.system()} {platform.release()}"]
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if branch:
        dirty = _git(root, "status", "--porcelain")
        n_dirty = len([ln for ln in dirty.splitlines() if ln.strip()])
        lines.append(f"Git branch: {branch} ({n_dirty} uncommitted file(s))")
        log = _git(root, "log", "-5", "--pretty=format:%h %s")
        if log:
            lines.append("Recent commits:\n" + log)
    lines.append("Files:")
    for e in _file_map(root, max_entries):
        lines.append(f"- {e}")
    return "\n".join(lines)
