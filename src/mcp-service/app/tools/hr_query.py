"""HR query tool - HTTP proxy sang hr-service."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from app.core.config import McpSettings
from app.tools.base import register_tool


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

    async def _call(self, user_id: str, intent: str) -> dict[str, Any]:
        client = self._get_client()
        response = await client.post(
            "/hr/query",
            json={"user_id": user_id, "intent": intent},
            headers=self._headers(),
        )
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

