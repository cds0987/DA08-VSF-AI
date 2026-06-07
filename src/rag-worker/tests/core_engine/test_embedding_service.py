from __future__ import annotations

import pytest

from core_engine.embedding.service import ProviderEmbeddingService


class _BatchingProvider:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str], dimension=None):
        self.calls.append(list(texts))
        return [[float(index)] for index, _ in enumerate(texts, start=1)]


@pytest.mark.asyncio
async def test_embedding_service_splits_large_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBED_BATCH_SIZE", "2")
    provider = _BatchingProvider()
    service = ProviderEmbeddingService(provider, dimension=3)

    vectors = await service.embed_batch(["a", "b", "c", "d", "e"])

    assert provider.calls == [["a", "b"], ["c", "d"], ["e"]]
    assert len(vectors) == 5
