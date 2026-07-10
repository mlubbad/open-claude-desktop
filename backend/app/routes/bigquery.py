"""BigQuery connectivity status + in-app ADC reconnect (gcloud re-login)."""
from __future__ import annotations

import subprocess

from fastapi import APIRouter, Depends
from ocd_core import auth_flows, bigquery, config

from ..deps import current_user

router = APIRouter(prefix="/bigquery")


@router.get("/status")
def status(user: str = Depends(current_user)) -> dict:
    """Probe BigQuery via a cheap dry-run. If creds look expired, rebuild the
    client once (they may have just been refreshed by /reconnect) and retry."""
    ok, _stmt, _bytes, _refs, err = bigquery._dry_run("SELECT 1")
    if not ok and bigquery.needs_reauth(err or ""):
        bigquery.reset_bq_client()
        ok, _stmt, _bytes, _refs, err = bigquery._dry_run("SELECT 1")
    return {
        "connected": ok,
        "project": config.PROJECT_ID,
        "auth_expired": (not ok) and bigquery.needs_reauth(err or ""),
        "error": None if ok else err,
    }


@router.post("/reconnect")
def reconnect(user: str = Depends(current_user)) -> dict:
    """Trigger `gcloud auth application-default login` (loopback browser flow) and
    drop the cached client so the next call rebuilds from the refreshed ADC."""
    # Resolve to a spawn-ready argv (absolute path; cmd-wrapped on Windows for the
    # gcloud.cmd shim) — a bare "gcloud" raises WinError 2 on Windows.
    argv = auth_flows.spawn_argv(["gcloud", "auth", "application-default", "login"])
    if argv is None:
        return {"started": False,
                "error": "gcloud CLI not found. Run "
                         "`gcloud auth application-default login` manually."}
    subprocess.Popen(argv)
    bigquery.reset_bq_client()
    return {"started": True}
