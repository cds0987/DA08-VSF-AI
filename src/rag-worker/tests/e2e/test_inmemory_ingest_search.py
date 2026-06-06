"""E2E: inline-markdown -> engine thật (offline embed) -> Qdrant in-memory -> vector payload.

Chứng minh luồng MVP (single-replica + inline markdown + Qdrant `:memory:`) chạy
end-to-end mà KHÔNG cần OpenAI / Qdrant remote / Postgres. Bổ sung cho các test
stub ở tầng use-case/router: ở đây engine, embedder, vectorstore đều là đồ thật.

Offline provider dùng embedding hash (không ngữ nghĩa); suite này chỉ chứng minh
plumbing ingest -> upsert -> payload/lineage, không kiểm search quality.
"""

from __future__ import annotations

import pytest

from core_engine import IngestInput, OfflineProvider, build_engine
from core_engine.vectorstore import VectorStoreConfig
from tests.e2e._vector_helpers import payloads_for_document


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

    payloads = payloads_for_document(engine, "doc-mvp-1")
    assert len(payloads) == 2
    assert all(payload["document_name"] == "MVP Guide" for payload in payloads)
    assert all(payload["source_uri"] for payload in payloads)
    assert all(payload["artifact_uri"] for payload in payloads)
    assert any("uvicorn" in payload["parent_text"] for payload in payloads)


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
    before_count = len(payloads_for_document(engine, "doc-prune"))
    assert before_count > 1

    await engine.ingest(
        IngestInput(
            document_id="doc-prune",
            document_name="Prune Guide",
            file_type="md",
            markdown="# Title\nshort body only\n",
        )
    )
    after_count = len(payloads_for_document(engine, "doc-prune"))

    assert after_count < before_count
