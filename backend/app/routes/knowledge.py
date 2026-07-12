from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from ocd_core import knowledge

from ..deps import current_user

router = APIRouter()


@router.post("/projects/{pid}/files")
def upload(pid: str, file: UploadFile = File(...), user: str = Depends(current_user)) -> dict:
    path = knowledge.save_uploaded_file(pid, file.filename, file.file.read())
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


@router.get("/files")
def all_files(limit: int = 500, user: str = Depends(current_user)) -> list[dict]:
    return knowledge.list_all_files(limit)
