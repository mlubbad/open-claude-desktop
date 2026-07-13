from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import current_user

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@router.get("/diagnostics")
def diagnostics(user: str = Depends(current_user)) -> dict:
    """A redacted operational snapshot for 'Export diagnostics' / bug reports. Gated
    (unlike /healthz): it exposes settings + data counts, though never any secret."""
    from ocd_core import diagnostics as diag
    return diag.collect()


@router.get("/readyz")
def readyz() -> dict:
    from ocd_core.db.engine import get_engine
    try:
        get_engine().connect().close()
        return {"status": "ready"}
    except Exception as e:
        return {"status": "unavailable", "error": str(e)}
