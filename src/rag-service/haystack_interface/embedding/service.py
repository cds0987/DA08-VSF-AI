"""ProviderEmbeddingService — port EmbeddingService chạy qua AI gateway.

Một implementation duy nhất cho cả offline lẫn OpenAI: nó chỉ gọi
`provider.embed(...)`. Chế độ (hash/offline vs OpenAI SDK) do provider singleton
quyết định — service này không biết và không cần biết (embedding.md §0).

Ingest caption-embed & search query-embed đi qua CÙNG service/provider/dimension
(search.md §2) — đảm bảo bằng kiến trúc, không bằng kỷ luật.
"""

from __future__ import annotations

from typing import List, Optional

from app.domain.repositories.embedding_service import EmbeddingService

from haystack_interface.ai import AIProvider, get_ai_provider


class ProviderEmbeddingService(EmbeddingService):
    def __init__(self, provider: AIProvider | None = None, *, dimension: Optional[int] = None):
        self._provider = provider or get_ai_provider()
        self._dim = dimension

    async def embed(self, text: str) -> List[float]:
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        return await self._provider.embed(texts, dimension=self._dim)
