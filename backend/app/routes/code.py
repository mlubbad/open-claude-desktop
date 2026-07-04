"""Code workspace routes — read-only file tree + file contents for the desktop Code tab.
The workspace is the per-project sandbox the agent's file tools edit."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from ocd_core import workspace

from ..deps import current_user

router = APIRouter()


@router.get("/code/tree")
def code_tree(project: str | None = None, user: str = Depends(current_user)) -> dict:
    """Flat, sorted file tree for the workspace (skips build/vendor dirs)."""
    return {"project": project or "general", "entries": workspace.list_tree(project)}


@router.get("/code/file")
def code_file(path: str, project: str | None = None, user: str = Depends(current_user)) -> dict:
    """Contents of one workspace file (traversal-jailed; binary files return no text)."""
    return workspace.read_file(project, path)
