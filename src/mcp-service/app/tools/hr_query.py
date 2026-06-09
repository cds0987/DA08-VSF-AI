"""HR query tool - HTTP proxy sang hr-service."""
from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from typing import Any

import httpx

from app.core.config import McpSettings
from app.tools.base import register_tool

logger = logging.getLogger("mcp-service")
MVP_INTENTS = {"leave_balance", "leave_requests", "attendance", "onboarding"}


def _mask_user_id(user_id: str) -> str:
    value = user_id.strip()
    if not value:
        return "unknown"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


class HrQueryTool:
    name = "hr_query"

    def __init__(self, settings: McpSettings, params: Mapping[str, Any]) -> None:
        nested = dict(params.get("params") or {})
        self._base_url = str(nested.get("hr_service_url") or "").strip().rstrip("/")
        self._token = str(nested.get("internal_token") or "").strip()
        self._client: httpx.AsyncClient | None = None

    def _headers(self) -> dict[str, str]:
        return {"X-Internal-Token": self._token} if self._token else {}

    def _get_client(self) -> httpx.AsyncClient:
        if not self._base_url:
            raise RuntimeError("hr_query: hr_service_url is not configured")
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._base_url, timeout=10.0)
        return self._client

    def _unsupported_intent_response(self, intent: str) -> dict[str, Any]:
        return {
            "intent": intent,
            "data": {},
            "summary": f"Intent '{intent}' chưa được hỗ trợ.",
        }

    def _not_found_response(self, intent: str) -> dict[str, Any]:
        return {
            "intent": intent,
            "data": {},
            "summary": "Bạn chưa có dữ liệu HR cho mục này.",
        }

    async def _call(self, user_id: str, intent: str) -> dict[str, Any]:
        masked_user = _mask_user_id(user_id)
        if intent not in MVP_INTENTS:
            logger.info("hr_query intent=%s user=%s status=unsupported_intent", intent, masked_user)
            return self._unsupported_intent_response(intent)

        client = self._get_client()
        response = await client.post(
            "/hr/query",
            json={"user_id": user_id, "intent": intent},
            headers=self._headers(),
        )
        if response.status_code == 404:
            logger.info("hr_query intent=%s user=%s status=404", intent, masked_user)
            return self._not_found_response(intent)

        logger.info("hr_query intent=%s user=%s status=%s", intent, masked_user, response.status_code)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("hr_query: invalid response payload")
        return body

    def register(self, mcp: Any) -> None:
        @mcp.tool()
        async def hr_query(user_id: str, intent: str) -> dict[str, Any]:
            return await self._call(user_id, intent)

    async def verify(self) -> None:
        client = self._get_client()
        response = await client.get("/health", headers=self._headers())
        response.raise_for_status()

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


register_tool("hr_query", lambda settings, params: HrQueryTool(settings, params))

