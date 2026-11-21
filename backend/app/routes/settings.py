from __future__ import annotations

from fastapi import APIRouter, Depends
from ocd_core import opik_tracing, settings

from ..deps import current_user
from ..schemas import SettingsBody

router = APIRouter()


@router.get("/settings")
def get_settings(user: str = Depends(current_user)) -> dict:
    return settings.get_settings()


@router.put("/settings")
def put_settings(body: SettingsBody, user: str = Depends(current_user)) -> dict:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    saved = settings.save_settings(patch)
    if any(k.startswith("opik_") for k in patch):
        # The tracing failure latch is one-way by design; a deliberate opik config
        # change is the signal that the setup deserves a fresh attempt.
        opik_tracing.invalidate()
    if patch.get("autonomy_paused") is True:
        # Kill-switch flipped on: stop the automations already in flight, not just new
        # ones. (Scheduler + the Cowork route block new launches while paused.)
        from ocd_core import cowork
        cowork.manager.cancel_all_running()
    return saved
