"""leave_types tool — danh mục loại nghỉ phép CHÍNH THỨC (4 rổ luật LĐ VN).

Read-only, proxy hr-service GET /hr/leave-types (nguồn sự thật = Leave Type Registry
ở hr-service). Dùng để agent trả lời "có những loại nghỉ phép nào" theo CHÍNH SÁCH,
KHÔNG suy từ lịch sử đơn của user. Không cần user_id (taxonomy chung, không nhạy cảm).
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import httpx

from app.core.config import McpSettings
from app.tools.base import register_tool

logger = logging.getLogger("mcp-service")


class LeaveTypesTool:
    name = "leave_types"

    def __init__(self, settings: McpSettings, params: Mapping[str, Any]) -> None:
        nested = dict(params.get("params") or {})
        self._base_url = str(nested.get("hr_service_url") or "").strip().rstrip("/")
        self._token = str(nested.get("internal_token") or "").strip()
        self._client: httpx.AsyncClient | None = None

    def _headers(self) -> dict[str, str]:
        return {"X-Internal-Token": self._token} if self._token else {}

    def _get_client(self) -> httpx.AsyncClient:
        if not self._base_url:
            raise RuntimeError("leave_types: hr_service_url is not configured")
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._base_url, timeout=10.0)
        return self._client

    def register(self, mcp: Any) -> None:
        @mcp.tool()
        async def leave_types(user_id: str = "") -> dict[str, Any]:
            """Danh mục loại nghỉ phép chính thức của công ty (4 rổ luật LĐ VN): mỗi loại
            kèm nhãn, nguồn trả lương, quỹ bị trừ, định mức/đơn. Dùng khi user hỏi 'có
            những loại nghỉ phép nào', 'các loại nghỉ', 'công ty có kiểu nghỉ gì'. Read-only.
            """
            client = self._get_client()
            response = await client.get("/hr/leave-types", headers=self._headers())
            logger.info("leave_types status=%s", response.status_code)
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("leave_types: invalid response payload")
            return body

    async def verify(self) -> None:
        if not self._base_url:
            logger.warning("leave_types verify skipped: hr_service_url chưa cấu hình")
            return
        try:
            client = self._get_client()
            response = await client.get("/health", headers=self._headers())
            response.raise_for_status()
            logger.info("leave_types verify ok hr_service=%s", self._base_url)
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.warning("leave_types verify degraded: %s", exc)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


register_tool("leave_types", lambda settings, params: LeaveTypesTool(settings, params))
