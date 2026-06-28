from __future__ import annotations

from fastapi import APIRouter, Depends
from ocd_core import settings

from ..deps import current_user

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


# Temporary settings probe (moved to routes/settings.py in Task 5)
@router.get("/settings")
def get_settings(user: str = Depends(current_user)) -> dict:
    return settings.get_settings()
