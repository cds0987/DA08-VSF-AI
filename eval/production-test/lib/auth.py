from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings
from .writer import utc_now


@dataclass
class AuthStats:
    refresh_count: int = 0
    relogin_count: int = 0


@dataclass
class AuthState:
    access_token: str
    refresh_token: str | None
    token_type: str
    user: dict[str, Any]
    access_exp: int | None
    logged_in_at: str


class AuthSession:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.http = http_client
        self.stats = AuthStats()
        self._state: AuthState | None = None
        self._lock = asyncio.Lock()

    @property
    def user(self) -> dict[str, Any]:
        if not self._state:
            raise RuntimeError("AuthSession is not logged in")
        return self._state.user

    @property
    def user_id(self) -> str:
        user_id = str(self.user.get("id") or "")
        if not user_id:
            raise RuntimeError("/auth/me did not return a user id")
        return user_id

    async def login(self, *, count_relogin: bool = False) -> None:
        async with self._lock:
            if self._state is None and (self.settings.prod_access_token or self.settings.prod_refresh_token):
                bootstrapped = await self._bootstrap_from_env_token_locked()
                if bootstrapped:
                    return
            await self._login_locked(count_relogin=count_relogin)

    async def ensure_valid(self, *, margin_seconds: int = 60) -> None:
        if not self._state:
            await self.login()
            return
        if self._state.access_exp and self._state.access_exp - time.time() <= margin_seconds:
            await self.recover()

    async def recover(self) -> bool:
        async with self._lock:
            if not self._state:
                await self._login_locked(count_relogin=True)
                return True
            if self._state.refresh_token:
                try:
                    response = await self.http.post(
                        f"{self.settings.user_base_url}/auth/refresh",
                        headers=self._base_headers(),
                        json={"refresh_token": self._state.refresh_token},
                    )
                    response.raise_for_status()
                    payload = response.json()
                    self._state.access_token = str(payload["access_token"])
                    self._state.refresh_token = payload.get("refresh_token") or self._state.refresh_token
                    self._state.token_type = str(payload.get("token_type") or "bearer")
                    self._state.access_exp = _jwt_exp(self._state.access_token)
                    self.stats.refresh_count += 1
                    return True
                except Exception:  # noqa: BLE001
                    pass
            await self._login_locked(count_relogin=True)
            return True

    async def auth_headers(self) -> dict[str, str]:
        await self.ensure_valid()
        if not self._state:
            raise RuntimeError("AuthSession is not logged in")
        return {
            **self._base_headers(),
            "Authorization": f"Bearer {self._state.access_token}",
        }

    def public_auth_info(self) -> dict[str, Any]:
        if not self._state:
            return {"logged_in": False}
        user = self._state.user
        return {
            "logged_in": True,
            "logged_in_at": self._state.logged_in_at,
            "user": {
                "id": user.get("id"),
                "email": user.get("email"),
                "role": user.get("role"),
                "account_type": user.get("account_type"),
                "department": user.get("department"),
            },
        }

    async def _login_locked(self, *, count_relogin: bool) -> None:
        response = await self.http.post(
            f"{self.settings.user_base_url}/auth/login",
            headers=self._base_headers(),
            json={"email": self.settings.prod_email, "password": self.settings.prod_password},
        )
        response.raise_for_status()
        token_payload = response.json()
        access_token = str(token_payload["access_token"])
        refresh_token = token_payload.get("refresh_token")
        me = await self.http.get(
            f"{self.settings.user_base_url}/auth/me",
            headers={
                **self._base_headers(),
                "Authorization": f"Bearer {access_token}",
            },
        )
        me.raise_for_status()
        self._state = AuthState(
            access_token=access_token,
            refresh_token=str(refresh_token) if refresh_token else None,
            token_type=str(token_payload.get("token_type") or "bearer"),
            user=me.json(),
            access_exp=_jwt_exp(access_token),
            logged_in_at=utc_now(),
        )
        if count_relogin:
            self.stats.relogin_count += 1

    async def _bootstrap_from_env_token_locked(self) -> bool:
        access_token = self.settings.prod_access_token
        refresh_token = self.settings.prod_refresh_token
        if access_token:
            try:
                me = await self.http.get(
                    f"{self.settings.user_base_url}/auth/me",
                    headers={
                        **self._base_headers(),
                        "Authorization": f"Bearer {access_token}",
                    },
                )
                me.raise_for_status()
                self._state = AuthState(
                    access_token=access_token,
                    refresh_token=refresh_token,
                    token_type="bearer",
                    user=me.json(),
                    access_exp=_jwt_exp(access_token),
                    logged_in_at=utc_now(),
                )
                return True
            except Exception:  # noqa: BLE001
                pass
        if refresh_token:
            try:
                response = await self.http.post(
                    f"{self.settings.user_base_url}/auth/refresh",
                    headers=self._base_headers(),
                    json={"refresh_token": refresh_token},
                )
                response.raise_for_status()
                payload = response.json()
                new_access = str(payload["access_token"])
                new_refresh = str(payload.get("refresh_token") or refresh_token)
                me = await self.http.get(
                    f"{self.settings.user_base_url}/auth/me",
                    headers={
                        **self._base_headers(),
                        "Authorization": f"Bearer {new_access}",
                    },
                )
                me.raise_for_status()
                self._state = AuthState(
                    access_token=new_access,
                    refresh_token=new_refresh,
                    token_type=str(payload.get("token_type") or "bearer"),
                    user=me.json(),
                    access_exp=_jwt_exp(new_access),
                    logged_in_at=utc_now(),
                )
                self.stats.refresh_count += 1
                return True
            except Exception:  # noqa: BLE001
                pass
        return False

    def _base_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.settings.gateway_basic_auth:
            headers["Authorization-Gateway"] = self.settings.gateway_basic_auth
        return headers


def _jwt_exp(token: str) -> int | None:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
        exp = data.get("exp")
        return int(exp) if exp is not None else None
    except Exception:  # noqa: BLE001
        return None
