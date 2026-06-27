"""ProviderEmbeddingService — port EmbeddingService chạy qua AI gateway.

Một implementation duy nhất cho cả offline lẫn OpenAI: nó chỉ gọi
`provider.embed(...)`. Chế độ (hash/offline vs OpenAI SDK) do provider singleton
quyết định — service này không biết và không cần biết (embedding.md §0).

Ingest caption-embed & search query-embed đi qua CÙNG service/provider/dimension
(search.md §2) — đảm bảo bằng kiến trúc, không bằng kỷ luật.

bm2 (2026-06-27): embed_batch chia sub-batch (EMBED_BATCH_SIZE) NHƯNG trước đây gọi
`for ... await` TUẦN TỰ -> doc 450 chunk = 5 call nối tiếp ×~18s = 92s (nghẽn dominant
đo per-doc). Router dưới (embed_or AIMD, 3 provider) gánh SONG SONG được -> dùng
`asyncio.gather` + AdaptiveConcurrencyLimiter (AIMD, mirror OCR) để embed sub-batch song
song, tự co khi 429. GIỮ thứ tự (gather theo index list sub-batch). 1 sub-batch (vd embed
query lẻ) -> gọi thẳng, không overhead.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import List, Optional

from core_engine.ai import AIProvider, get_ai_provider
from core_engine.concurrency import AdaptiveConcurrencyLimiter
from core_engine.logging_utils import log_event
from core_engine.types import EmbeddingService


class ProviderEmbeddingService(EmbeddingService):
    def __init__(self, provider: AIProvider | None = None, *, dimension: Optional[int] = None):
        self._provider = provider or get_ai_provider()
        self._dim = dimension
        self._batch_size = max(1, int(os.getenv("EMBED_BATCH_SIZE", "100")))
        self._logger = logging.getLogger(__name__)
        # Song song hóa sub-batch qua AI Router elastic. max = trần concurrency embed toàn
        # service (singleton, chia mọi worker). AIMD tự co khi TransientAIError(429/overload).
        max_limit = max(1, int(os.getenv("EMBED_BATCH_MAX_CONCURRENCY", "24")))
        min_limit = max(1, min(max_limit, int(os.getenv("EMBED_BATCH_MIN_CONCURRENCY", "4"))))
        initial = int(os.getenv("EMBED_BATCH_INITIAL_CONCURRENCY", str(min(max_limit, 8))))
        self._limiter = AdaptiveConcurrencyLimiter(
            initial=initial,
            min_limit=min_limit,
            max_limit=max_limit,
            grow_after_successes=max(1, int(os.getenv("EMBED_GROW_AFTER", "3"))),
            shrink_factor=float(os.getenv("EMBED_SHRINK_FACTOR", "0.5")),
            on_resize=self._on_concurrency_resize,
            logger=self._logger,
        )

    def _on_concurrency_resize(self, event: str, limit: int) -> None:
        log_event(
            self._logger,
            logging.INFO,
            f"embed_concurrency_{event}",
            stage="embed",
            limit=limit,
        )

    async def embed(self, text: str) -> List[float]:
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        sub_batches = [
            texts[start : start + self._batch_size]
            for start in range(0, len(texts), self._batch_size)
        ]
        if len(sub_batches) == 1:
            # 1 sub-batch (vd query lẻ) -> gọi thẳng, không gather/limiter overhead.
            return await self._provider.embed(sub_batches[0], dimension=self._dim)

        async def _one(batch: List[str]) -> List[List[float]]:
            async with self._limiter.slot():
                return await self._provider.embed(batch, dimension=self._dim)

        # gather GIỮ thứ tự sub_batches -> flatten đúng thứ tự chunk gốc. return_exceptions
        # mặc định False -> 1 sub-batch fail thì cả embed_batch fail (đúng: doc fail rõ ràng).
        results = await asyncio.gather(*(_one(batch) for batch in sub_batches))
        vectors: List[List[float]] = []
        for part in results:
            vectors.extend(part)
        return vectors
