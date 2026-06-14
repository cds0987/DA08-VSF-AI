"""HTTP client gọi hr-service cho luồng Leave WRITE (REST path).

query-service xác thực JWT của user -> inject user_id/approver_user_id (KHÔNG tin
client) -> gọi hr-service bằng X-Internal-Token. Trả (status_code, body) thô để
router map lỗi nghiệp vụ (403/404/409/422) nguyên vẹn cho frontend.

KHÔNG dùng MCP cho luồng này: approve/reject/pending-approval theo thiết kế là HTTP
nội bộ (không phải MCP tool), nên 1 HTTP client trực tiếp là gọn + đúng nhất.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("query-service")


class HRLeaveClient:
    def __init__(self, settings: Any) -> None:
        self._base_url = str(settings.hr_service_url or "").strip().rstrip("/")
        self._token = (settings.hr_internal_token or "").strip()
        self._timeout = float(getattr(settings, "hr_http_timeout_seconds", 10.0))

    def _headers(self) -> dict[str, str]:
        return {"X-Internal-Token": self._token} if self._token else {}

    async def _request(
        self, method: str, path: str, *, json: dict | None = None, params: dict | None = None
    ) -> tuple[int, dict]:
        if not self._base_url:
            raise RuntimeError("hr_service_url chưa cấu hình")
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.request(
                method, f"{self._base_url}{path}", json=json, params=params, headers=self._headers()
            )
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            body = {}
        if not isinstance(body, dict):
            body = {"items": body}
        return resp.status_code, body

    async def create(
        self,
        *,
        user_id: str,
        leave_type: str,
        start_date: str,
        end_date: str,
        reason: str,
        idempotency_key: str | None = None,
    ) -> tuple[int, dict]:
        payload: dict[str, Any] = {
            "user_id": user_id,
            "leave_type": leave_type,
            "start_date": start_date,
            "end_date": end_date,
            "reason": reason,
        }
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key
        return await self._request("POST", "/hr/leave-requests", json=payload)

    async def cancel(self, *, user_id: str, request_id: str) -> tuple[int, dict]:
        return await self._request(
            "POST", f"/hr/leave-requests/{request_id}/cancel", json={"user_id": user_id}
        )

    async def list_pending_approval(self, *, approver_user_id: str) -> tuple[int, dict]:
        return await self._request(
            "GET", "/hr/leave-requests/pending-approval",
            params={"approver_user_id": approver_user_id},
        )

    async def decide(
        self, *, request_id: str, approver_user_id: str, action: str, reason: str = ""
    ) -> tuple[int, dict]:
        if action not in ("approve", "reject"):
            raise ValueError(f"action không hợp lệ: {action}")
        return await self._request(
            "POST", f"/hr/leave-requests/{request_id}/{action}",
            json={"approver_user_id": approver_user_id, "reason": reason},
        )
