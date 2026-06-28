from __future__ import annotations

from fastapi import APIRouter, Depends
from ocd_core import settings

from ..deps import current_user
from ..schemas import SettingsBody

router = APIRouter()


@router.get("/settings")
def get_settings(user: str = Depends(current_user)) -> dict:
    return settings.get_settings()


@router.put("/settings")
def put_settings(body: SettingsBody, user: str = Depends(current_user)) -> dict:
    return settings.save_settings({k: v for k, v in body.model_dump().items() if v is not None})
