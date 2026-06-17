"""leave_approvals tool — đọc HÀNG ĐỢI DUYỆT của người đang đăng nhập (approver).

Khác hr_query (trả hồ sơ HR của CHÍNH user). Tool này trả các đơn nghỉ mà user là
NGƯỜI DUYỆT (approver_user_id = user_id), đang chờ duyệt. Read-only, proxy hr-service.

`user_id` do query-service inject từ JWT (KHÔNG tin LLM) -> dùng làm approver_user_id.
Approve/reject KHÔNG ở đây — đó là REST có xác nhận ở FE (thẻ Duyệt/Từ chối).
"""
from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from typing import Any

import httpx

from app.core.config import McpSettings
from app.tools.base import register_tool

logger = logging.getLogger("mcp-service")


def _mask_user_id(user_id: str) -> str:
    value = user_id.strip()
    if not value:
        return "unknown"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


class LeaveApprovalsTool:
    name = "leave_approvals"

    def __init__(self, settings: McpSettings, params: Mapping[str, Any]) -> None:
        nested = dict(params.get("params") or {})
        self._base_url = str(nested.get("hr_service_url") or "").strip().rstrip("/")
        self._token = str(nested.get("internal_token") or "").strip()
        self._client: httpx.AsyncClient | None = None

    def _headers(self) -> dict[str, str]:
        return {"X-Internal-Token": self._token} if self._token else {}

    def _get_client(self) -> httpx.AsyncClient:
        if not self._base_url:
            raise RuntimeError("leave_approvals: hr_service_url is not configured")
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._base_url, timeout=10.0)
        return self._client

    def register(self, mcp: Any) -> None:
        @mcp.tool()
        async def leave_approvals(user_id: str) -> dict[str, Any]:
            """Liệt kê các đơn nghỉ phép ĐANG CHỜ user hiện tại DUYỆT (user là người
            duyệt). Dùng khi sếp/quản lý hỏi 'đơn nào chờ tôi duyệt', 'tôi cần duyệt
            bao nhiêu đơn', 'ai đang xin nghỉ'. Read-only.

            Trả {items: [...], count: N}. Mỗi item gồm id (request_id), user_id (nhân
            viên), leave_type, start_date, end_date, days_count, reason, status.
            """
            client = self._get_client()
            masked = _mask_user_id(user_id)
            response = await client.get(
                "/hr/leave-requests/pending-approval",
                params={"approver_user_id": user_id},
                headers=self._headers(),
            )
            logger.info("leave_approvals approver=%s status=%s", masked, response.status_code)
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("leave_approvals: invalid response payload")
            return body

    async def verify(self) -> None:
        # Best-effort y hệt hr_query: hr-service tạm down KHÔNG làm sập mcp-service.
        if not self._base_url:
            logger.warning("leave_approvals verify skipped: hr_service_url chưa cấu hình")
            return
        try:
            client = self._get_client()
            response = await client.get("/health", headers=self._headers())
            response.raise_for_status()
            logger.info("leave_approvals verify ok hr_service=%s", self._base_url)
        except Exception as exc:  # noqa: BLE001 — chủ ý nuốt mọi lỗi health (best-effort)
            logger.warning(
                "leave_approvals verify degraded: hr-service không reachable (%s) — "
                "tool vẫn đăng ký, call sẽ best-effort",
                exc,
            )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


register_tool("leave_approvals", lambda settings, params: LeaveApprovalsTool(settings, params))
