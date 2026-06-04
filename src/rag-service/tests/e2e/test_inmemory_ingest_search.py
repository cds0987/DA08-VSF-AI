"""E2E: inline-markdown -> engine thật (offline embed) -> Qdrant in-memory -> search.

Chứng minh luồng MVP (single-replica + inline markdown + Qdrant `:memory:`) chạy
end-to-end mà KHÔNG cần OpenAI / Qdrant remote / Postgres. Bổ sung cho các test
stub ở tầng use-case/router: ở đây engine, embedder, vectorstore đều là đồ thật.

Offline provider dùng embedding hash (không ngữ nghĩa) nên test chấm điểm theo
rerank lexical với `caption=False` + `rerank_threshold=0.0` — đủ để kiểm plumbing
(ingest -> upsert -> search -> rerank -> contract fields), không kiểm chất lượng.
"""

from __future__ import annotations

import pytest

from core_engine import IngestInput, OfflineProvider, build_engine
from core_engine.vectorstore import VectorStoreConfig


def _build_inmemory_engine():
    provider = OfflineProvider(256)
    vector_config = VectorStoreConfig(provider="qdrant", url="")  # url rỗng => in_process :memory:
    return build_engine(provider=provider, vector_config=vector_config, caption=False)


@pytest.mark.asyncio
async def test_inline_markdown_ingests_to_qdrant_memory_and_is_searchable() -> None:
    engine = _build_inmemory_engine()
    assert engine.vectors.config.deployment == "in_process"

    chunk_count = await engine.ingest(
        IngestInput(
            document_id="doc-mvp-1",
            document_name="MVP Guide",
            file_type="md",
            markdown=(
                "# Hướng dẫn cài đặt\n"
                "Để chạy dịch vụ, đặt biến môi trường rồi khởi động uvicorn.\n\n"
                "# Khắc phục sự cố\n"
                "Nếu readiness trả 503, kiểm tra provider AI và vector backend.\n"
            ),
            correlation_id="cid-e2e-1",
        )
    )
    assert chunk_count == 2

    results = await engine.search(
        "khởi động uvicorn", rerank_threshold=0.0, correlation_id="cid-e2e-1"
    )

    assert results, "search phải trả ít nhất 1 kết quả từ Qdrant in-memory"
    top = results[0]
    assert top.correlation_id == "cid-e2e-1"
    assert top.document_id == "doc-mvp-1"
    assert top.unit_id.startswith("doc-mvp-1::p")
    assert top.display_name == "MVP Guide"
    assert top.content
    assert top.lineage.source_uri
    assert top.lineage.artifact_uri
    # Chunk khớp từ khóa truy vấn phải xếp trên chunk không liên quan.
    assert "uvicorn" in top.content


@pytest.mark.asyncio
async def test_reingest_same_document_prunes_stale_chunks_in_memory() -> None:
    engine = _build_inmemory_engine()

    await engine.ingest(
        IngestInput(
            document_id="doc-prune",
            document_name="Prune Guide",
            file_type="md",
            markdown="# Title\n" + "alpha " * 300,
        )
    )
    before = await engine.search("alpha", rerank_threshold=0.0, top_k=10)
    before_count = len([r for r in before if r.document_id == "doc-prune"])
    assert before_count > 1

    await engine.ingest(
        IngestInput(
            document_id="doc-prune",
            document_name="Prune Guide",
            file_type="md",
            markdown="# Title\nshort body only\n",
        )
    )
    after = await engine.search("alpha", rerank_threshold=0.0, top_k=10)
    after_count = len([r for r in after if r.document_id == "doc-prune"])

    assert after_count < before_count


@pytest.mark.asyncio
async def test_search_returns_empty_for_unknown_collection() -> None:
    engine = _build_inmemory_engine()

    results = await engine.search("không có gì được index", rerank_threshold=0.0)

    assert results == []
