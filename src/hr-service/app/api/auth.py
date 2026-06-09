from __future__ import annotations

import hmac

from fastapi import Depends, Header, HTTPException

from app.core.config import HrSettings, get_settings


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
