from __future__ import annotations

import pytest

from core_engine.config import HaystackSettings
from core_engine.engine import (
    CaptionFallbackThresholdExceededError,
    ChunkLimitExceededError,
    HaystackRagEngine,
    IngestInput,
)


class _StubEmbedder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, text: str):
        return [1.0]

    async def embed_batch(self, texts: list[str]):
        self.calls.append(texts)
        return [[float(index)] for index, _ in enumerate(texts, start=1)]


class _StubVectors:
    def __init__(self, existing: list[str] | None = None) -> None:
        self.existing = existing or []
        self.upserted = []
        self.deleted_batches: list[list[str]] = []

    async def list_chunk_ids_by_document(self, document_id: str) -> list[str]:
        return list(self.existing)

    async def upsert_many(self, records) -> None:
        self.upserted = list(records)

    async def delete_many(self, chunk_ids: list[str]) -> None:
        self.deleted_batches.append(list(chunk_ids))

    async def delete_by_document(self, document_id: str) -> None:
        raise NotImplementedError


class _StubCaptioner:
    async def caption(self, text: str) -> str:
        return f"caption:{text.split()[0]}"


class _FallbackCaptioner:
    async def caption_with_metadata(self, text: str):
        return type("CaptionResult", (), {"text": text[:10], "used_fallback": True})()


@pytest.mark.asyncio
async def test_engine_keeps_child_windows_when_captioner_enabled() -> None:
    vectors = _StubVectors()
    engine = HaystackRagEngine(
        HaystackSettings(embed_dimension=3, parent_max_words=100, child_max_words=4, child_overlap_words=1),
        _StubEmbedder(),
        vectors,
        captioner=_StubCaptioner(),
    )

    chunk_count = await engine.ingest(
        IngestInput(
            document_id="doc-1",
            document_name="Doc",
            file_type="md",
            markdown="# Title\none two three four five six seven eight nine ten",
        )
    )

    assert chunk_count > 1
    assert len(vectors.upserted) == chunk_count
    assert all(record.payload["child_text"].startswith("caption:") for record in vectors.upserted)
    assert all(record.payload["bm25_text"] != record.payload["child_text"] for record in vectors.upserted)


@pytest.mark.asyncio
async def test_engine_prunes_existing_vectors_when_ingest_has_no_chunks() -> None:
    vectors = _StubVectors(existing=["doc-1::p0::c0", "doc-1::p0::c1"])
    engine = HaystackRagEngine(
        HaystackSettings(embed_dimension=3, parent_max_words=10, child_max_words=5, child_overlap_words=1),
        _StubEmbedder(),
        vectors,
    )

    chunk_count = await engine.ingest(
        IngestInput(
            document_id="doc-1",
            document_name="Doc",
            file_type="md",
            markdown="",
        )
    )

    assert chunk_count == 0
    assert vectors.deleted_batches == [["doc-1::p0::c0", "doc-1::p0::c1"]]


@pytest.mark.asyncio
async def test_engine_rejects_document_exceeding_chunk_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_CHUNKS_PER_DOC", "1")
    vectors = _StubVectors()
    engine = HaystackRagEngine(
        HaystackSettings(embed_dimension=3, parent_max_words=100, child_max_words=4, child_overlap_words=1),
        _StubEmbedder(),
        vectors,
    )

    with pytest.raises(ChunkLimitExceededError):
        await engine.ingest(
            IngestInput(
                document_id="doc-1",
                document_name="Doc",
                file_type="md",
                markdown="# Title\none two three four five six seven eight nine ten",
            )
        )


@pytest.mark.asyncio
async def test_engine_fails_when_caption_fallback_rate_exceeds_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAPTION_FALLBACK_THRESHOLD", "0.1")
    vectors = _StubVectors()
    engine = HaystackRagEngine(
        HaystackSettings(embed_dimension=3, parent_max_words=100, child_max_words=4, child_overlap_words=1),
        _StubEmbedder(),
        vectors,
        captioner=_FallbackCaptioner(),
    )

    with pytest.raises(CaptionFallbackThresholdExceededError):
        await engine.ingest(
            IngestInput(
                document_id="doc-1",
                document_name="Doc",
                file_type="md",
                markdown="# Title\none two three four five six seven eight nine ten",
            )
        )
