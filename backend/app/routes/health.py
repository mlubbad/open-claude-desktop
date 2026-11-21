from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

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
def readyz():
    """Readiness for orchestration/monitors. 503 (not 200) when the DB is unreachable OR
    when we're silently serving the SQLite fallback because the configured DB was down —
    so a degraded instance is taken out of rotation instead of accepting writes against
    the wrong store. (The desktop shell polls /healthz, not this, so a local user on the
    default SQLite — never a fallback — always sees ready.)"""
    from ocd_core.db import engine
    try:
        engine.get_engine().connect().close()
    except Exception as e:
        return JSONResponse({"status": "unavailable", "error": str(e)}, status_code=503)
    if engine.fell_back():
        return JSONResponse(
            {"status": "degraded",
             "detail": "serving the local SQLite fallback; the configured database was unreachable",
             "configured_backend": engine.database_url().split(":", 1)[0],
             "active_backend": engine.active_database_url().split(":", 1)[0]},
            status_code=503)
    return {"status": "ready"}
