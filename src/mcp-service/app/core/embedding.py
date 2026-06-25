"""Embed query - MCP-local implementation for offline hash and OpenAI.

@150-burst: MỖI rag_search embed riêng -> 611 embed call (storm) -> embed (OpenRouter qwen) nghẽn
-> rag treo 22s. FIX: CoalescingEmbedder gom các embed() ĐỒNG THỜI (cửa sổ ~15ms) thành 1 call
`embeddings.create(input=[N query])` (API hỗ trợ, đo: batch-30 1.7s vs 30-single 3.9s) -> scatter
kết quả về từng caller. 611 embed -> ~vài chục. Flag embed_coalesce (tắt = per-call cũ).
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Protocol

from app.core.config import McpSettings
from app.core.text_utils import hash_embed

logger = logging.getLogger(__name__)


def _is_router_down(exc: Exception) -> bool:
    """Lỗi nghi router (base_url) chết: connection/timeout/5xx -> đáng fallback direct.
    KHÔNG fallback lỗi 4xx (bad request) — đó là lỗi thật, fallback chỉ che."""
    name = type(exc).__name__.lower()
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and status >= 500:
        return True
    return any(s in name for s in ("connection", "timeout", "internalserver", "apiconnection"))


class QueryEmbedder(Protocol):
    async def embed(self, text: str) -> List[float]: ...


class OfflineEmbedder:
    def __init__(self, dimension: int) -> None:
        self._dim = dimension

    async def embed(self, text: str) -> List[float]:
        return hash_embed([text], self._dim)[0]

    async def embed_many(self, texts: List[str]) -> List[List[float]]:
        return hash_embed(list(texts), self._dim)


class OpenAIEmbedder:
    def __init__(self, *, model: str, dimension: int, api_key: str, base_url: str,
                 fallback_api_key: str = "", fallback_base_url: str = "") -> None:
        self._model = model
        self._dim = dimension
        self._api_key = api_key
        self._base_url = base_url or None
        self._client = None
        # Fallback direct OpenAI khi router (base_url) chết. Trống = TẮT.
        self._fb_api_key = fallback_api_key
        self._fb_base_url = fallback_base_url or None
        self._fb_client = None

    def _openai_client(self):
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=self._api_key or None, base_url=self._base_url)
        return self._client

    def _fallback_client(self):
        """Direct OpenAI (key dự phòng) — chỉ dựng khi có cấu hình fallback."""
        if not self._fb_api_key:
            return None
        if self._fb_client is None:
            from openai import AsyncOpenAI

            self._fb_client = AsyncOpenAI(api_key=self._fb_api_key, base_url=self._fb_base_url)
        return self._fb_client

    async def aclose(self) -> None:
        for attr in ("_client", "_fb_client"):
            client = getattr(self, attr)
            setattr(self, attr, None)
            if client is not None:
                await client.close()

    async def _create(self, client, payload):
        # payload: str (1 query) hoặc list[str] (batch). API embeddings nhận cả 2.
        return await client.embeddings.create(model=self._model, input=payload, dimensions=self._dim)

    async def _embed_payload(self, payload):
        try:
            return await self._create(self._openai_client(), payload)
        except Exception as exc:  # noqa: BLE001
            fb = self._fallback_client()
            if fb is None or not _is_router_down(exc):
                raise
            # Router down + có fallback -> gọi thẳng OpenAI để search KHÔNG sập.
            logger.warning("embed_router_fallback_direct err=%s", str(exc)[:160])
            return await self._create(fb, payload)

    async def embed(self, text: str) -> List[float]:
        response = await self._embed_payload(text)
        return list(response.data[0].embedding)

    async def embed_many(self, texts: List[str]) -> List[List[float]]:
        """Batch: input=[N query] -> N embedding. Sắp theo .index (API không đảm bảo thứ tự)."""
        response = await self._embed_payload(list(texts))
        ordered = sorted(response.data, key=lambda d: getattr(d, "index", 0))
        return [list(d.embedding) for d in ordered]


class CoalescingEmbedder:
    """Gom embed() ĐỒNG THỜI (cửa sổ ngắn / tới max_batch) -> 1 call embed_many -> scatter.
    Diệt embed-storm @burst. mcp 1 event-loop -> thao tác list/pending ATOMIC giữa các await."""

    def __init__(self, inner, *, max_batch: int = 32, window_ms: int = 15) -> None:
        self._inner = inner
        self._max_batch = max(1, max_batch)
        self._window = max(0, window_ms) / 1000.0
        self._pending: list = []          # [(text, future)]
        self._timer: asyncio.Task | None = None

    async def embed(self, text: str) -> List[float]:
        fut = asyncio.get_running_loop().create_future()
        self._pending.append((text, fut))
        if len(self._pending) >= self._max_batch:
            self._flush()
        elif self._timer is None:
            self._timer = asyncio.create_task(self._flush_after())
        return await fut

    async def embed_many(self, texts: List[str]) -> List[List[float]]:
        return await self._inner.embed_many(texts)

    async def _flush_after(self) -> None:
        try:
            await asyncio.sleep(self._window)
        except asyncio.CancelledError:
            return
        self._flush()

    def _flush(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if not self._pending:
            return
        batch = self._pending
        self._pending = []
        asyncio.create_task(self._run(batch))

    async def _run(self, batch: list) -> None:
        texts = [t for t, _ in batch]
        try:
            vecs = await self._inner.embed_many(texts)
        except Exception as exc:  # noqa: BLE001 — fail tất cả caller trong batch (mỗi cái tự retry)
            for _, fut in batch:
                if not fut.done():
                    fut.set_exception(exc)
            return
        if len(vecs) != len(batch):
            err = RuntimeError(f"embed batch size mismatch: {len(vecs)} != {len(batch)}")
            for _, fut in batch:
                if not fut.done():
                    fut.set_exception(err)
            return
        for (_, fut), vec in zip(batch, vecs):
            if not fut.done():
                fut.set_result(vec)

    async def aclose(self) -> None:
        self._flush()
        inner_close = getattr(self._inner, "aclose", None)
        if callable(inner_close):
            await inner_close()


def build_embedder(settings: McpSettings) -> QueryEmbedder:
    if settings.embed_model == "offline":
        return OfflineEmbedder(settings.dimension)
    base = OpenAIEmbedder(
        model=settings.embed_model,
        dimension=settings.dimension,
        api_key=settings.embed_api_key or settings.api_key,
        base_url=settings.embed_base_url,
        fallback_api_key=settings.embed_fallback_api_key,
        fallback_base_url=settings.embed_fallback_base_url,
    )
    if getattr(settings, "embed_coalesce", True):
        return CoalescingEmbedder(
            base,
            max_batch=getattr(settings, "embed_coalesce_max", 32),
            window_ms=getattr(settings, "embed_coalesce_window_ms", 15),
        )
    return base
