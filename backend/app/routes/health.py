from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
def readyz() -> dict:
    from ocd_core.db.engine import get_engine
    try:
        get_engine().connect().close()
        return {"status": "ready"}
    except Exception as e:
        return {"status": "unavailable", "error": str(e)}
