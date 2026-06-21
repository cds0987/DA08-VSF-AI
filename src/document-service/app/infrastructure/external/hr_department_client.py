"""Tra department của user SỐNG từ hr-service (NGUỒN SỰ THẬT) cho ACL secret-doc.

Vì sao: department do HR quản (user-service đã bỏ khỏi token — migration 0002). Trước đây
document-service đọc department từ JWT -> luôn rỗng -> ACL secret theo phòng ban CHẾT. Client
này lấy department thật từ hr-service thay vì token.

Thiết kế "ít vỡ nhất":
- Dùng endpoint CÔNG KHAI `GET /hr/employees/departments` (không cần token) -> chỉ document-service
  đổi, không đụng hr-service.
- Cache TTL ngắn (mặc định 30s) -> mở file secret nhiều lần không gọi HR mỗi lần.
- Lỗi / HR down -> trả "" (giữ cache cũ nếu có) -> ACL secret fail-closed (an toàn, KHÔNG mở nhầm).
- Bọc trong 1 client -> sau muốn đổi sang projection/event chỉ sửa chỗ này.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class HrDepartmentClient:
    def __init__(
        self,
        base_url: str,
        ttl_seconds: int = 30,
        timeout_seconds: float = 4.0,
        *,
        transport: Any | None = None,  # test inject httpx.MockTransport
    ) -> None:
        self._url = base_url.rstrip("/") + "/hr/employees/departments"
        self._ttl = ttl_seconds
        self._timeout = timeout_seconds
        self._transport = transport
        self._cache: dict[str, str] = {}
        self._fetched_at = 0.0

    async def get_department(self, user_id: str) -> str:
        """department hiện tại của user theo HR. Không thấy / lỗi -> "" (fail-closed)."""
        await self._refresh_if_stale()
        return self._cache.get(str(user_id), "")

    async def _refresh_if_stale(self) -> None:
        now = time.monotonic()
        if self._cache and (now - self._fetched_at) < self._ttl:
            return
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.get(self._url)
            if resp.status_code == 200:
                items: list[dict[str, Any]] = (resp.json() or {}).get("items") or []
                self._cache = {
                    str(it.get("user_id")): str(it.get("department") or "")
                    for it in items
                    if it.get("user_id")
                }
                self._fetched_at = now
        except Exception as exc:  # noqa: BLE001 — HR down KHÔNG được làm sập doc-service
            # Giữ cache cũ (nếu có) -> không tự dưng mất quyền vì 1 lần HR chớp nhoáng.
            logger.warning("hr_department_fetch_failed: %s", str(exc)[:160])
