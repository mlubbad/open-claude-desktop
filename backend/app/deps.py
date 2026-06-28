from __future__ import annotations
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from ocd_core import auth

_bearer = HTTPBearer(auto_error=False)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    """Optional auth: when disabled (no creds configured) -> 'anonymous'.
    When enabled -> require a valid Bearer token (decode to username), else 401."""
    if not auth.auth_enabled():
        return "anonymous"
    user = auth.decode_token(creds.credentials) if creds else None
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing token")
    return user
