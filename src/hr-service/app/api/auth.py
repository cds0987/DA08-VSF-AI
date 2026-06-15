from __future__ import annotations

import hmac
from jose import JWTError, jwt

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.core.config import HrSettings, get_settings


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def verify_internal_token(
    expected: str,
    provided: str,
) -> None:
    if not expected:
        return
    if not hmac.compare_digest(expected.encode("utf-8"), provided.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid internal token")


def require_internal_token(
    settings: HrSettings = Depends(get_settings),
    x_internal_token: str = Header(default="", alias="X-Internal-Token"),
) -> None:
    verify_internal_token(settings.internal_token, x_internal_token)


def require_admin_jwt(
    token: str = Depends(oauth2_scheme),
    settings: HrSettings = Depends(get_settings),
) -> dict:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing token",
        )
    try:
        # User Service uses HS256 by default (from common.env JWT_ALGORITHM)
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=["HS256"],
        )
        role = payload.get("role")
        if role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin only",
            )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
