"""Search query-side trên Qdrant in-process (đồ THẬT) — dense + hybrid + ACL + mapping.

Port logic từ mcp reader về rag-worker; suite này chốt:
  - search trả candidate đã map đúng field (caption fallback, source_uri->source_gcs_uri,
    artifact_uri->markdown_gcs_uri, heading_path, page_number, score).
  - ACL: document_ids None/rỗng -> filter __no_access__ -> kết quả RỖNG.
  - chạy được trên CẢ collection hybrid (named dense+sparse) lẫn dense trần (unnamed).
"""

from __future__ import annotations

import pytest

from core_engine.vectorstore.config import VectorStoreConfig
from core_engine.vectorstore.providers.qdrant.inprocess import QdrantInProcessRepository
from core_engine.vectorstore.types import VectorRecord


def _records() -> list[VectorRecord]:
    return [
        VectorRecord(
            chunk_id="c1",
            vector=[1.0, 0.0, 0.0, 0.0],
            payload={
                "chunk_id": "c1",
                "document_id": "d1",
                "document_name": "Sổ tay",
                # KHÔNG có "caption" -> phải fallback về child_text.
                "child_text": "hello world",
                "parent_text": "parent of c1",
                "heading_path": ["Chương 1"],
                "page_number": 3,
                "source_uri": "gs://bucket/source.pdf",
                "artifact_uri": "gs://bucket/source.md",
                "bm25_text": "hello world",
            },
        ),
        VectorRecord(
            chunk_id="c2",
            vector=[0.0, 1.0, 0.0, 0.0],
            payload={
                "chunk_id": "c2",
                "document_id": "d2",
                "document_name": "Tài liệu khác",
                "caption": "ảnh bảng lương",
                "child_text": "row data",
                "parent_text": "parent of c2",
                "heading_path": [],
                "page_number": None,
                "source_uri": "gs://bucket/other.pdf",
                "artifact_uri": "gs://bucket/other.md",
                "bm25_text": "row data",
            },
        ),
    ]


async def _seed(hybrid: bool) -> QdrantInProcessRepository:
    config = VectorStoreConfig(provider="qdrant", url="", dimension=4, hybrid=hybrid)
    repo = QdrantInProcessRepository(config)
    await repo.upsert_many(_records())
    return repo


@pytest.mark.asyncio
@pytest.mark.parametrize("hybrid", [False, True])
async def test_search_returns_mapped_candidates(hybrid: bool) -> None:
    repo = await _seed(hybrid)

    hits = await repo.search(
        query_vector=[1.0, 0.0, 0.0, 0.0],
        query_text="hello",
        top_k=10,
        document_ids=["d1"],
    )

    assert len(hits) == 1
    hit = hits[0]
    assert hit.chunk_id == "c1"
    assert hit.document_id == "d1"
    assert hit.document_name == "Sổ tay"
    # caption fallback child_text (payload không có "caption").
    assert hit.caption == "hello world"
    assert hit.child_text == "hello world"
    assert hit.parent_text == "parent of c1"
    assert hit.heading_path == ["Chương 1"]
    assert hit.page_number == 3
    # source_uri -> source_gcs_uri; artifact_uri -> markdown_gcs_uri.
    assert hit.source_gcs_uri == "gs://bucket/source.pdf"
    assert hit.markdown_gcs_uri == "gs://bucket/source.md"
    assert isinstance(hit.score, float)


@pytest.mark.asyncio
@pytest.mark.parametrize("hybrid", [False, True])
async def test_search_uses_explicit_caption_when_present(hybrid: bool) -> None:
    repo = await _seed(hybrid)

    hits = await repo.search(
        query_vector=[0.0, 1.0, 0.0, 0.0],
        query_text="row",
        top_k=10,
        document_ids=["d2"],
    )

    assert len(hits) == 1
    assert hits[0].caption == "ảnh bảng lương"
    assert hits[0].page_number is None


@pytest.mark.asyncio
@pytest.mark.parametrize("hybrid", [False, True])
async def test_search_acl_empty_document_ids_returns_nothing(hybrid: bool) -> None:
    repo = await _seed(hybrid)

    none_result = await repo.search(
        query_vector=[1.0, 0.0, 0.0, 0.0],
        query_text="hello",
        top_k=10,
        document_ids=None,
    )
    empty_result = await repo.search(
        query_vector=[1.0, 0.0, 0.0, 0.0],
        query_text="hello",
        top_k=10,
        document_ids=[],
    )

    # ACL fail-closed: rỗng/None -> __no_access__ -> KHÔNG có ứng viên nào.
    assert none_result == []
    assert empty_result == []


@pytest.mark.asyncio
@pytest.mark.parametrize("hybrid", [False, True])
async def test_search_scopes_to_allowed_documents(hybrid: bool) -> None:
    repo = await _seed(hybrid)

    # Cho phép cả d1 + d2: filter MatchAny -> không rò doc ngoài danh sách.
    hits = await repo.search(
        query_vector=[1.0, 0.0, 0.0, 0.0],
        query_text="hello",
        top_k=10,
        document_ids=["d1", "d2"],
    )
    returned_docs = {hit.document_id for hit in hits}
    assert returned_docs <= {"d1", "d2"}

    # Chỉ cho phép d2 -> d1 KHÔNG được trả dù vector khớp d1.
    only_d2 = await repo.search(
        query_vector=[1.0, 0.0, 0.0, 0.0],
        query_text="hello",
        top_k=10,
        document_ids=["d2"],
    )
    assert all(hit.document_id == "d2" for hit in only_d2)
