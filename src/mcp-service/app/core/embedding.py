"""Embed query - MCP-local implementation for offline hash and OpenAI."""

from __future__ import annotations

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

    async def _create(self, client, text: str):
        return await client.embeddings.create(model=self._model, input=text, dimensions=self._dim)

    async def embed(self, text: str) -> List[float]:
        try:
            response = await self._create(self._openai_client(), text)
        except Exception as exc:  # noqa: BLE001
            fb = self._fallback_client()
            if fb is None or not _is_router_down(exc):
                raise
            # Router down + có fallback -> gọi thẳng OpenAI để search KHÔNG sập.
            logger.warning("embed_router_fallback_direct err=%s", str(exc)[:160])
            response = await self._create(fb, text)
        return list(response.data[0].embedding)


def build_embedder(settings: McpSettings) -> QueryEmbedder:
    if settings.embed_model == "offline":
        return OfflineEmbedder(settings.dimension)
    return OpenAIEmbedder(
        model=settings.embed_model,
        dimension=settings.dimension,
        api_key=settings.embed_api_key or settings.api_key,
        base_url=settings.embed_base_url,
        fallback_api_key=settings.embed_fallback_api_key,
        fallback_base_url=settings.embed_fallback_base_url,
    )
