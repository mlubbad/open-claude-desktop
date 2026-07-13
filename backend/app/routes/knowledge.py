from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from ocd_core import knowledge

from ..deps import current_user

router = APIRouter()


@router.post("/projects/{pid}/files")
def upload(pid: str, file: UploadFile = File(...), user: str = Depends(current_user)) -> dict:
    try:
        raw = knowledge.read_upload(file.file)   # bounded read — reject a huge upload
    except knowledge.UploadTooLarge as e:
        raise HTTPException(413, str(e)) from e
    path = knowledge.save_uploaded_file(pid, file.filename, raw)
    try:
        chunks = knowledge.ingest_file_to_kb(pid, path)
    except knowledge.ExtractionError as e:
        # The file is kept (visible in the project), but the user must know it
        # didn't ingest — the old behavior indexed nothing without a word.
        raise HTTPException(422, f"'{file.filename}' was saved but could not be "
                                 f"indexed: {e}") from e
    return {"ok": True, "name": file.filename, "chunks": chunks}


@router.get("/projects/{pid}/files")
def list_files(pid: str, user: str = Depends(current_user)) -> list[dict]:
    return knowledge.list_project_files(pid)


@router.delete("/projects/{pid}/files/{name}")
def delete_file(pid: str, name: str, user: str = Depends(current_user)) -> dict:
    """Remove ONE knowledge file + its KB chunks (P1-11)."""
    if not knowledge.delete_project_file(pid, name):
        raise HTTPException(404, "no such file")
    return {"ok": True, "name": name}


@router.post("/projects/{pid}/files/{name}/reindex")
def reindex_file(pid: str, name: str, user: str = Depends(current_user)) -> dict:
    """Purge + re-ingest ONE knowledge file (e.g. after an extraction fix)."""
    try:
        chunks = knowledge.reindex_project_file(pid, name)
    except knowledge.ExtractionError as e:
        raise HTTPException(422, f"'{name}' could not be indexed: {e}") from e
    if chunks < 0:
        raise HTTPException(404, "no such file")
    return {"ok": True, "name": name, "chunks": chunks}


@router.get("/files")
def all_files(limit: int = 500, user: str = Depends(current_user)) -> list[dict]:
    return knowledge.list_all_files(limit)
