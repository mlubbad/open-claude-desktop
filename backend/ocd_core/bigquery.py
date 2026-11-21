"""BigQuery client + SQL validation/execution (read-only analytics policy).

Moved verbatim from legacy_frontend/core.py (get_bq_client, _dry_run,
execute_sql). Behavior parity is the contract — the only changes are import
references:
  * config.* / util.fmt_bytes for the bare names core.py imported at module top
  * ocd_core.sql_guard.check_banned_aliases (already the shared guard in core.py)
  * ocd_core.projects.get_project_allowlist for the per-project allowlist check
  * ocd_core.observability.observe in place of the local core._observe (the two
    are behavior-identical — confirmed in a prior slice)

NOTE: started as a faithful move of the Reflex execute_sql. The per-project
allowlist guard (sql_guard.tables_off_allowlist) is now wired in here, hardened
to parsed referenced_tables from the dry-run so commented/quoted table names
can't bypass it. The salvaged rate-limit (observability.check_rate_limit) guard
is still deliberately NOT wired in — it stays available for a later phase.
"""
from __future__ import annotations

import json
import threading
import time

from . import config, util
from .observability import observe
from .projects import get_project_allowlist
from .sql_guard import check_banned_aliases, tables_off_allowlist

_bq_client = None
_bq_lock = threading.Lock()


def get_bq_client():
    global _bq_client
    with _bq_lock:
        if _bq_client is None:
            import google.auth
            from google.cloud import bigquery
            credentials, _ = google.auth.default()
            _bq_client = bigquery.Client(project=config.PROJECT_ID, credentials=credentials)
        return _bq_client


_REAUTH_SIGNATURES = (
    "reauthentication is needed",
    "reauthentication failed",
    "invalid_grant",
    "refresherror",
    "invalid_rapt",
    "could not automatically determine credentials",
)


def needs_reauth(err: str) -> bool:
    """True when an error string indicates ADC credentials need re-login.

    Used to flag agent/SQL results as ``auth_expired`` so the UI can offer an
    in-app "Reconnect Google" action instead of a generic failure.
    """
    e = (err or "").lower()
    return any(sig in e for sig in _REAUTH_SIGNATURES)


def reset_bq_client() -> None:
    """Drop the cached client so the next get_bq_client() rebuilds from fresh ADC.

    Called after an in-app reconnect (gcloud ADC re-login) so the new credentials
    take effect without a process restart.
    """
    global _bq_client
    with _bq_lock:
        _bq_client = None


def _dry_run(sql: str):
    from google.cloud.bigquery import QueryJobConfig
    client = get_bq_client()
    try:
        job = client.query(sql, QueryJobConfig(dry_run=True, use_query_cache=False))
        stmt = getattr(job, "statement_type", None) or "UNKNOWN"
        refs = [f"{t.dataset_id}.{t.table_id}" for t in (job.referenced_tables or [])]
        return True, stmt, job.total_bytes_processed or 0, refs, None
    except Exception as e:
        return False, None, 0, [], str(e)


def execute_sql(sql: str, active_project: str | None = None) -> dict:
    """Validate + run a query. Read-only policy: only SELECT executes.

    Returns a structured result:
      {ok, stmt, columns, rows, total_rows, truncated, bytes, agent_text, error}
    `agent_text` is what the LLM sees; `rows`/`columns` drive the UI table.
    """
    from google.cloud.bigquery import QueryJobConfig
    sql = (sql or "").strip()
    t0 = time.time()
    if not sql:
        return {"ok": False, "error": "empty", "agent_text": "No SQL provided."}

    alias_err = check_banned_aliases(sql)
    if alias_err:
        return {"ok": False, "error": "alias", "agent_text": f"SQL REJECTED: {alias_err}"}

    ok, stmt, est_bytes, refs, err = _dry_run(sql)
    if not ok:
        return {"ok": False, "stmt": stmt, "error": err, "auth_expired": needs_reauth(err),
                "agent_text": f"VALIDATION FAILED (0 rows scanned). Fix and retry.\nError: {err}"}

    if active_project:
        allow = get_project_allowlist(active_project)
        if tables_off_allowlist(refs, allow):
            return {"ok": False, "error": "allowlist",
                    "agent_text": f"SQL REJECTED: project allows only: {', '.join(allow)}"}

    if stmt != "SELECT":
        return {"ok": False, "stmt": stmt, "error": "mutation_blocked",
                "agent_text": (f"REJECTED: {stmt} statements are disabled in the chat agent "
                               f"(read-only analytics). Rewrite as a SELECT.")}

    if est_bytes > config.MAX_BYTES_BILLED:
        return {"ok": False, "stmt": stmt, "error": "cost",
                "agent_text": (f"REFUSED: estimated scan {util.fmt_bytes(est_bytes)} exceeds the cap "
                               f"{util.fmt_bytes(config.MAX_BYTES_BILLED)}. Add partition/date filters.")}

    try:
        client = get_bq_client()
        job = client.query(sql, QueryJobConfig(maximum_bytes_billed=config.MAX_BYTES_BILLED))
        rows_iter = job.result(timeout=config.QUERY_TIMEOUT_SEC)
        billed = job.total_bytes_billed or job.total_bytes_processed or 0
        rows = []
        for r in rows_iter:
            rows.append(dict(r))
            if len(rows) >= config.MAX_STORED_ROWS:
                break
        total = rows_iter.total_rows if rows_iter.total_rows is not None else len(rows)
        truncated = total > len(rows)
        columns = list(rows[0].keys()) if rows else []
        preview = rows[:config.MAX_RETURN_ROWS]
        header = (f"[{total} rows; showing first {len(preview)}]"
                  if total > len(preview) else f"[{total} rows]")
        agent_text = f"{header} scanned {util.fmt_bytes(billed)}\n{json.dumps(preview, default=str)}"
        observe("query_ok", rows=total, bytes=billed, latency_s=round(time.time() - t0, 2))
        return {"ok": True, "stmt": stmt, "columns": columns, "rows": rows,
                "total_rows": total, "truncated": truncated, "bytes": billed,
                "agent_text": agent_text}
    except Exception as e:
        observe("query_fail", error=str(e))
        return {"ok": False, "stmt": stmt, "error": str(e),
                "agent_text": f"EXECUTION FAILED: {e}. Fix the SQL and try again."}
