"""UsageReconciler (MOSA) — lúc boot, ĐỌC usage THẬT của key từ provider để KHÔNG
"mù" (default 0). Vấn đề: counter Redis có thể lệch (bypass/undercount/Redis wipe) ->
thuật toán tưởng key còn nhiều. Reconciler lấy số thật từ provider làm đối chiếu.

Khả thi theo provider:
  - OpenRouter: GET /api/v1/key trả {usage, limit} (credit đã dùng) -> đọc được.
  - OpenAI:     KHÔNG có endpoint per-key token real-time -> bỏ qua (dựa 429-as-truth
                + khống chế hết để counter đầy đủ).

MOSA: thêm provider = thêm 1 class implement UsageReconciler + 1 dòng build_reconcilers.
Best-effort: lỗi mạng KHÔNG làm sập boot. Inject `fetch` để test offline.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from .registry import Registry
from .schemas import Provider

logger = logging.getLogger("ai_router.reconcile")

FetchFn = Callable[[str], Awaitable[dict]]


class UsageReconciler(ABC):
    provider: str

    @abstractmethod
    async def reconcile(self, registry: Registry) -> list[dict]:
        """Trả [{key_id, usage, limit, ...}] cho các key của provider này (đã log)."""


class OpenRouterReconciler(UsageReconciler):
    provider = "openrouter"

    def __init__(self, fetch: FetchFn | None = None) -> None:
        self._fetch = fetch or self._http_fetch

    async def reconcile(self, registry: Registry) -> list[dict]:
        out: list[dict] = []
        for key in registry.keys_for_provider(Provider.OPENROUTER):
            secret = registry.secret(key)
            if not secret:
                continue
            try:
                info = await self._fetch(secret)
                row = {"key_id": key.id, "provider": "openrouter", **info}
                out.append(row)
                logger.info("reconcile_usage", extra=row)
            except Exception as exc:  # noqa: BLE001 — best-effort, không sập boot
                logger.warning("reconcile_failed key=%s err=%s", key.id, str(exc)[:160])
        return out

    @staticmethod
    async def _http_fetch(secret: str) -> dict:
        import httpx  # noqa: PLC0415 — chỉ import khi thật sự reconcile

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://openrouter.ai/api/v1/key",
                headers={"Authorization": f"Bearer {secret}"},
            )
            resp.raise_for_status()
            data = resp.json().get("data", {}) or {}
            return {"usage": float(data.get("usage") or 0.0), "limit": data.get("limit")}


def build_reconcilers(settings) -> list[UsageReconciler]:
    """MOSA registry reconciler. OpenAI bỏ qua (không có endpoint per-key)."""
    return [OpenRouterReconciler()]
