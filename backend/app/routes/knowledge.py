from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from ocd_core import knowledge

from ..deps import current_user

router = APIRouter()


@router.post("/projects/{pid}/files")
def upload(pid: str, file: UploadFile = File(...), user: str = Depends(current_user)) -> dict:
    path = knowledge.save_uploaded_file(pid, file.filename, file.file.read())
    chunks = knowledge.ingest_file_to_kb(pid, path)
    return {"ok": True, "name": file.filename, "chunks": chunks}


@router.get("/projects/{pid}/files")
def list_files(pid: str, user: str = Depends(current_user)) -> list[dict]:
    return knowledge.list_project_files(pid)


@router.get("/files")
def all_files(limit: int = 500, user: str = Depends(current_user)) -> list[dict]:
    return knowledge.list_all_files(limit)
