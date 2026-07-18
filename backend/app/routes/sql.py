from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from ocd_core import bigquery, observability

from ..deps import current_user
from ..schemas import SqlExecuteRequest

router = APIRouter(prefix="/sql")


@router.post("/execute")
def execute(body: SqlExecuteRequest, user: str = Depends(current_user)) -> dict:
    # Per-user rate limit before any BigQuery work (parity with /agent/turn). The
    # dataset-scope + read-only guards live in ocd_core.bigquery.execute_sql.
    if not observability.check_rate_limit(user):
        observability.audit({"event": "rate_limited", "user": user, "sql": body.sql[:200]})
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate limit exceeded")
    return bigquery.execute_sql(body.sql, body.project)
