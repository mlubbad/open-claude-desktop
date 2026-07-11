"""Observability (Opik) — status + the Cloud API key.

The key is written to the OS keychain via ``ocd_core.opik_tracing`` (which delegates
to ``ocd_core.secrets``) and is NEVER returned by any endpoint — only a ``has_key``
flag, mirroring the BYOK provider-key routes. Non-secret config (enabled / mode / url
/ project / workspace) lives in settings.json and is edited through ``/settings``.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from ocd_core import opik_tracing, settings
from pydantic import BaseModel

from ..deps import current_user

router = APIRouter()


class OpikKeyBody(BaseModel):
    key: str


@router.get("/observability")
def get_observability(user: str = Depends(current_user)) -> dict:
    """Everything the Settings UI needs to render the Observability section — with a
    ``has_key`` flag instead of the key itself, and whether the SDK is installed."""
    s = settings.get_settings()
    return {
        "enabled": bool(s.get("opik_enabled")),
        "mode": s.get("opik_mode") or "local",
        "url": s.get("opik_url") or "",
        "project": s.get("opik_project") or "open-claude-desktop",
        "workspace": s.get("opik_workspace") or "",
        "has_key": opik_tracing.has_api_key(),
        "sdk_installed": opik_tracing.sdk_installed(),
    }


@router.put("/observability/key")
def set_opik_key(body: OpikKeyBody, user: str = Depends(current_user)) -> dict:
    """Store the Opik Cloud API key in the OS keychain."""
    opik_tracing.set_api_key(body.key)
    return {"has_key": opik_tracing.has_api_key()}


@router.delete("/observability/key")
def delete_opik_key(user: str = Depends(current_user)) -> dict:
    opik_tracing.delete_api_key()
    return {"has_key": opik_tracing.has_api_key()}
