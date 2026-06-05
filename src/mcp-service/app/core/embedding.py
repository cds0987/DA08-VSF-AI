"""Embed query — BẢN RIÊNG mcp. Offline (hash tất định) + OpenAI.

Phải dùng CÙNG model/dimension với lúc ingest (rag-worker) — đảm bảo bởi contract
fingerprint + dấu niêm Qdrant. Offline copy đúng hash_embed (xem text_utils).
"""

from __future__ import annotations

from typing import List, Protocol

from app.core.config import McpSettings
from app.core.text_utils import hash_embed


class QueryEmbedder(Protocol):
    async def embed(self, text: str) -> List[float]: ...


class OfflineEmbedder:
    def __init__(self, dimension: int) -> None:
        self._dim = dimension

    async def embed(self, text: str) -> List[float]:
        return hash_embed([text], self._dim)[0]


class OpenAIEmbedder:
    def __init__(self, *, model: str, dimension: int, api_key: str, base_url: str) -> None:
        self._model = model
        self._dim = dimension
        self._api_key = api_key
        self._base_url = base_url or None

    async def embed(self, text: str) -> List[float]:
        # Lazy import: chỉ cần khi chạy provider thật.
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self._api_key or None, base_url=self._base_url)
        try:
            resp = await client.embeddings.create(
                model=self._model, input=text, dimensions=self._dim
            )
        finally:
            await client.close()
        return list(resp.data[0].embedding)


def build_embedder(settings: McpSettings) -> QueryEmbedder:
    if settings.embed_model == "offline":
        return OfflineEmbedder(settings.dimension)
    return OpenAIEmbedder(
        model=settings.embed_model,
        dimension=settings.dimension,
        api_key=settings.embed_api_key or settings.api_key,
        base_url=settings.embed_base_url,
    )
