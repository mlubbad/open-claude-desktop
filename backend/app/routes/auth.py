from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request, status
from ocd_core import auth, observability

from ..schemas import LoginRequest, TokenResponse

router = APIRouter(prefix="/auth")


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request) -> TokenResponse:
    # H1: throttle attempts per client so a single password can't be brute forced.
    client_key = request.client.host if request.client else "unknown"
    if not observability.check_login_rate_limit(client_key):
        observability.audit({"event": "login_rate_limited", "client": client_key})
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "too many login attempts; try again later")
    if not auth.credentials_ok(body.username, body.password):
        observability.audit({"event": "login_failed", "client": client_key})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad credentials")
    return TokenResponse(token=auth.make_token(body.username, int(time.time())))
