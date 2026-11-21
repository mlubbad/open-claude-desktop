"""Observability (Opik) — status + the Cloud API key.

The key is written to the OS keychain via ``ocd_core.opik_tracing`` (which delegates
to ``ocd_core.secrets``) and is NEVER returned by any endpoint — only a ``has_key``
flag, mirroring the BYOK provider-key routes. Non-secret config (enabled / mode / url
/ project / workspace) lives in settings.json and is edited through ``/settings``.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from ocd_core import opik_tracing
from pydantic import BaseModel

from ..deps import current_user

router = APIRouter()


class OpikKeyBody(BaseModel):
    key: str


@router.get("/observability")
def get_observability(user: str = Depends(current_user)) -> dict:
    """The Observability section's render state — ``has_key`` instead of the key.
    Field resolution (and its defaults) lives in opik_tracing.ui_status, not here."""
    return opik_tracing.ui_status()


@router.put("/observability/key")
def set_opik_key(body: OpikKeyBody, user: str = Depends(current_user)) -> dict:
    """Store the Opik Cloud API key in the OS keychain."""
    opik_tracing.set_api_key(body.key)
    return {"has_key": opik_tracing.has_api_key()}


@router.delete("/observability/key")
def delete_opik_key(user: str = Depends(current_user)) -> dict:
    opik_tracing.delete_api_key()
    return {"has_key": opik_tracing.has_api_key()}
