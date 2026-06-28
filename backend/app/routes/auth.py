from __future__ import annotations
import time
from fastapi import APIRouter, HTTPException, status
from ocd_core import auth
from ..schemas import LoginRequest, TokenResponse

router = APIRouter(prefix="/auth")


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest) -> TokenResponse:
    if not auth.credentials_ok(body.username, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad credentials")
    return TokenResponse(token=auth.make_token(body.username, int(time.time())))
