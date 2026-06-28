from __future__ import annotations

import asyncio

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

    # Mọi sub-batch được gọi (thứ tự sub-batch không bắt buộc vì gather song song).
    assert sorted(provider.calls) == sorted([["a", "b"], ["c", "d"], ["e"]])
    assert len(vectors) == 5


@pytest.mark.asyncio
async def test_embed_batch_runs_subbatches_in_parallel(monkeypatch: pytest.MonkeyPatch) -> None:
    """bm2: sub-batch chạy SONG SONG (gather), không tuần tự -> peak concurrency > 1."""
    monkeypatch.setenv("EMBED_BATCH_SIZE", "1")  # 4 text -> 4 sub-batch

    class _ConcurrencyProbe:
        def __init__(self) -> None:
            self.active = 0
            self.peak = 0

        async def embed(self, texts: list[str], dimension=None):
            self.active += 1
            self.peak = max(self.peak, self.active)
            await asyncio.sleep(0.05)  # giữ slot để các sub-batch khác chồng lên
            self.active -= 1
            return [[1.0] for _ in texts]

    provider = _ConcurrencyProbe()
    service = ProviderEmbeddingService(provider, dimension=1)
    await service.embed_batch(["a", "b", "c", "d"])
    assert provider.peak >= 2, f"sub-batch phải song song, peak={provider.peak} (tuần tự sẽ =1)"


@pytest.mark.asyncio
async def test_embed_batch_preserves_order_under_parallel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bằng chứng KHÔNG xáo trộn embedding: vector[i] phải khớp text[i] dù chạy song song +
    thời gian hoàn thành đảo (sub-batch sau xong trước)."""
    monkeypatch.setenv("EMBED_BATCH_SIZE", "1")

    class _OrderProvider:
        """embed(text) -> vector mã hóa độ dài text; sub-batch dài hoàn thành CHẬM hơn (đảo
        thứ tự xong) để chứng minh gather vẫn map đúng index."""

        async def embed(self, texts: list[str], dimension=None):
            await asyncio.sleep(0.01 * len(texts[0]))  # text dài -> xong sau
            return [[float(len(t))] for t in texts]

    service = ProviderEmbeddingService(_OrderProvider(), dimension=1)
    inputs = ["xxxxx", "x", "xxx", "xx", "xxxx"]  # độ dài lộn xộn -> thứ tự xong đảo
    vectors = await service.embed_batch(inputs)
    assert vectors == [[float(len(t))] for t in inputs]


@pytest.mark.asyncio
async def test_embed_batch_single_subbatch_calls_provider_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMBED_BATCH_SIZE", "100")
    provider = _BatchingProvider()
    service = ProviderEmbeddingService(provider, dimension=1)
    await service.embed_batch(["only"])
    assert provider.calls == [["only"]]


@pytest.mark.asyncio
async def test_embed_batch_propagates_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBED_BATCH_SIZE", "1")

    class _Boom:
        async def embed(self, texts: list[str], dimension=None):
            raise RuntimeError("boom")

    service = ProviderEmbeddingService(_Boom(), dimension=1)
    with pytest.raises(RuntimeError):
        await service.embed_batch(["a", "b", "c"])
