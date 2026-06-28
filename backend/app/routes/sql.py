from __future__ import annotations

from fastapi import APIRouter, Depends
from ocd_core import bigquery

from ..deps import current_user
from ..schemas import SqlExecuteRequest

router = APIRouter(prefix="/sql")


@router.post("/execute")
def execute(body: SqlExecuteRequest, user: str = Depends(current_user)) -> dict:
    return bigquery.execute_sql(body.sql, body.project)
