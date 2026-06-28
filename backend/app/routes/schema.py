from __future__ import annotations

from fastapi import APIRouter, Depends
from ocd_core import schema_catalog

from ..deps import current_user

router = APIRouter(prefix="/schema")


@router.get("/search")
def search(q: str, project: str | None = None, user: str = Depends(current_user)) -> dict:
    return {"result": schema_catalog.search_schema(q, active_project=project)}


@router.post("/rebuild")
def rebuild(user: str = Depends(current_user)) -> dict:
    n, errors = schema_catalog.ensure_catalog()
    return {"tables": n, "errors": errors}


@router.get("/status")
def status(user: str = Depends(current_user)) -> dict:
    return {"version_ok": schema_catalog._catalog_version_matches()}
