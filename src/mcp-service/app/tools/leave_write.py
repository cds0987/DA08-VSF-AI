"""Leave WRITE tools - HTTP proxy sang hr-service (tạo/sửa/hủy đơn nghỉ phép).

TÁCH HẲN khỏi hr_query (READ). Đăng ký 1 tool entry `leave_write` (1 cờ enable) expose
3 MCP function: create_leave_request / update_leave_request / cancel_leave_request.
mcp-service CHỈ proxy — KHÔNG validate nghiệp vụ (validate/transaction/balance là việc
hr-service). `user_id` do client (query-service) inject từ JWT — KHÔNG tin LLM.

Duyệt/từ chối (approve/reject) KHÔNG expose qua MCP — đó là HTTP nội bộ của UI/sếp.

Cờ TẮT mặc định (TOOL_LEAVE_WRITE_ENABLED=0) ở config.yaml — tránh footgun tự bật
(Bẫy 2). verify() best-effort: hr-service down KHÔNG làm sập mcp (kéo rag_search).
"""
from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from typing import Any, Literal, Optional

import httpx

from app.core.config import McpSettings
from app.tools.base import register_tool

logger = logging.getLogger("mcp-service")

# 4 rổ luật LĐ VN — khớp Leave Type Registry ở hr-service (app/domain/leave_policy.py).
# mcp chỉ proxy; hr-service validate cap/quỹ. 'personal' giữ cho tương thích đơn cũ.
LeaveType = Literal[
    "annual", "marriage", "child_marriage", "bereavement", "sick", "maternity", "unpaid", "personal",
]


def _mask_user_id(user_id: str) -> str:
    value = user_id.strip()
    if not value:
        return "unknown"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


class LeaveWriteTool:
    name = "leave_write"

    def __init__(self, settings: McpSettings, params: Mapping[str, Any]) -> None:
        nested = dict(params.get("params") or {})
        self._base_url = str(nested.get("hr_service_url") or "").strip().rstrip("/")
        self._token = str(nested.get("internal_token") or "").strip()
        self._client: httpx.AsyncClient | None = None

    def _headers(self) -> dict[str, str]:
        return {"X-Internal-Token": self._token} if self._token else {}

    def _get_client(self) -> httpx.AsyncClient:
        if not self._base_url:
            raise RuntimeError("leave_write: hr_service_url is not configured")
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._base_url, timeout=10.0)
        return self._client

    async def _request(self, method: str, path: str, payload: dict[str, Any], *, masked: str,
                       op: str) -> dict[str, Any]:
        """Proxy 1 request. 2xx -> trả body. 4xx -> trả lỗi có cấu trúc (để user/LLM
        thấy lý do: thiếu approver/đủ phép/không quyền...) thay vì crash. 5xx -> raise
        (transient, để caller retry/đánh dấu lỗi)."""
        client = self._get_client()
        response = await client.request(method, path, json=payload, headers=self._headers())
        code = response.status_code
        logger.info("leave_write op=%s user=%s status=%s", op, masked, code)
        if 200 <= code < 300:
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("leave_write: invalid response payload")
            return body
        if 400 <= code < 500:
            detail: Any
            try:
                detail = response.json().get("detail")
            except Exception:  # noqa: BLE001
                detail = response.text
            return {"ok": False, "status_code": code, "error": detail}
        response.raise_for_status()
        raise RuntimeError("unreachable")

    def register(self, mcp: Any) -> None:
        @mcp.tool()
        async def create_leave_request(
            user_id: str,
            leave_type: LeaveType,
            start_date: str,
            end_date: str,
            reason: str = "",
            idempotency_key: str = "",
        ) -> dict[str, Any]:
            """Tạo đơn xin nghỉ phép cho user hiện tại (đã được user xác nhận ở bước
            confirm phía trên). leave_type: annual|sick|personal. start_date/end_date
            dạng YYYY-MM-DD. Trả đơn vừa tạo (status='pending', approver_user_id).
            """
            payload: dict[str, Any] = {
                "user_id": user_id, "leave_type": leave_type,
                "start_date": start_date, "end_date": end_date, "reason": reason,
            }
            if idempotency_key:
                payload["idempotency_key"] = idempotency_key
            return await self._request("POST", "/hr/leave-requests", payload,
                                       masked=_mask_user_id(user_id), op="create")

        @mcp.tool()
        async def update_leave_request(
            user_id: str,
            request_id: str,
            leave_type: LeaveType,
            start_date: str,
            end_date: str,
            reason: str = "",
            idempotency_key: str = "",
        ) -> dict[str, Any]:
            """Sửa đơn nghỉ phép của user. Đơn còn pending -> sửa tại chỗ. Đơn đã duyệt
            -> hệ thống tự hủy đơn cũ (hoàn phép) và tạo đơn mới chờ duyệt lại. Trả đơn
            kết quả.
            """
            payload: dict[str, Any] = {
                "user_id": user_id, "leave_type": leave_type,
                "start_date": start_date, "end_date": end_date, "reason": reason,
            }
            if idempotency_key:
                payload["idempotency_key"] = idempotency_key
            return await self._request("PATCH", f"/hr/leave-requests/{request_id}", payload,
                                       masked=_mask_user_id(user_id), op="update")

        @mcp.tool()
        async def cancel_leave_request(user_id: str, request_id: str) -> dict[str, Any]:
            """Hủy đơn nghỉ phép của user. Nếu đơn đã được duyệt thì hoàn lại số ngày
            phép đã trừ. Trả đơn sau khi hủy.
            """
            return await self._request("POST", f"/hr/leave-requests/{request_id}/cancel",
                                       {"user_id": user_id},
                                       masked=_mask_user_id(user_id), op="cancel")

    async def verify(self) -> None:
        # Best-effort y hệt hr_query: hr-service tạm down KHÔNG làm sập mcp-service.
        if not self._base_url:
            logger.warning("leave_write verify skipped: hr_service_url chưa cấu hình")
            return
        try:
            client = self._get_client()
            response = await client.get("/health", headers=self._headers())
            response.raise_for_status()
            logger.info("leave_write verify ok hr_service=%s", self._base_url)
        except Exception as exc:  # noqa: BLE001 — chủ ý nuốt mọi lỗi health (best-effort)
            logger.warning(
                "leave_write verify degraded: hr-service không reachable (%s) — "
                "tool vẫn đăng ký, call sẽ best-effort",
                exc,
            )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


register_tool("leave_write", lambda settings, params: LeaveWriteTool(settings, params))
