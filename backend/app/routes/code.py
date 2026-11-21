"""Code workspace routes — read-only file tree + file contents for the desktop Code tab.
The workspace is the per-project sandbox the agent's file tools edit."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
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


@router.get("/code/download")
def code_download(path: str, project: str | None = None, user: str = Depends(current_user)):
    """Download one workspace file as raw bytes (traversal-jailed). Lets the client save a
    file a code_execution run produced — a chart PNG, an xlsx, the merged CSV."""
    target = workspace.file_path(project, path)
    if target is None:
        raise HTTPException(404, "file not found")
    return FileResponse(str(target), filename=target.name)
