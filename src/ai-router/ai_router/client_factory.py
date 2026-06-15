"""client_factory — cache AsyncOpenAI theo (base_url, api_key). PLAN §5.0b.

"Client động" = CHỌN client đã cache theo key resolve được, KHÔNG tạo mới mỗi request
(tránh thrash connection pool). N key = N client thường trú.
"""
from __future__ import annotations

from openai import AsyncOpenAI


class ClientFactory:
    def __init__(self, timeout: float = 60.0) -> None:
        self._timeout = timeout
        self._cache: dict[tuple[str, str], AsyncOpenAI] = {}

    def get(self, base_url: str | None, api_key: str) -> AsyncOpenAI:
        ck = (base_url or "", api_key)
        client = self._cache.get(ck)
        if client is None:
            kwargs: dict = {"api_key": api_key, "timeout": self._timeout, "max_retries": 0}
            if base_url:
                kwargs["base_url"] = base_url
            client = AsyncOpenAI(**kwargs)
            self._cache[ck] = client
        return client

    async def aclose(self) -> None:
        for c in self._cache.values():
            try:
                await c.close()
            except Exception:  # noqa: BLE001
                pass
        self._cache.clear()
