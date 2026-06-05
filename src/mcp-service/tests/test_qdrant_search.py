"""Qdrant reader contract tests without relying on local disk persistence."""

from __future__ import annotations

import asyncio

import pytest

from app.core.config import McpSettings
from app.core.contract import VectorstoreContractError
from app.core.embedding import OfflineEmbedder
from app.core.rerank import NoopReranker
from app.core.search import SearchService
from app.core.vectorstore import QdrantReader, SearchHit

DIM = 256
QUERY = "nghi phep thuong nien"


def _settings() -> McpSettings:
    return McpSettings(
        provider="qdrant",
        collection="rag_chatbot",
        embed_model="offline",
        dimension=DIM,
        url="",
        api_key="",
        embed_base_url="",
        embed_api_key="",
        rerank_impl="none",
        rerank_model="gpt-4o-mini",
        rerank_base_url="",
        rerank_api_key="",
        rerank_timeout_seconds=30.0,
        rerank_batch_size=8,
        rerank_passage_chars=800,
        top_k_candidates=20,
        rerank_top_k=3,
        rerank_threshold=0.0,
        options={},
    )


def _stamp(settings: McpSettings, *, fingerprint: str | None = None) -> dict[str, object]:
    contract = settings.contract()
    return {
        "kind": "__contract__",
        "index_id": contract.index_id,
        "fingerprint": fingerprint or contract.fingerprint,
        "provider": contract.provider,
        "collection": contract.collection,
        "embed_model": contract.embed_model,
        "dimension": contract.dimension,
        "schema_version": contract.schema_version,
    }


def test_verify_and_search_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    reader = QdrantReader(settings)
    monkeypatch.setattr(reader, "_fetch_local", lambda: (True, DIM, _stamp(settings)))
    monkeypatch.setattr(
        reader,
        "_search_local",
        lambda vector, top_k: [
            SearchHit(
                chunk_id="doc1::p0::c0",
                document_id="doc1",
                document_name="So tay nhan vien",
                caption="Nghi phep",
                parent_text="Chinh sach nghi phep thuong nien 12 ngay cho nhan vien",
                heading_path=["Phuc loi"],
                score=0.87,
                page_number=1,
                source_gcs_uri="gs://bucket/doc1.pdf",
                markdown_gcs_uri="gs://bucket/doc1.md",
            )
        ],
    )

    asyncio.run(reader.verify_contract())

    service = SearchService(settings, OfflineEmbedder(DIM), reader, NoopReranker())
    hits = asyncio.run(service.rag_search(QUERY, document_ids=["doc1"], top_k=3))
    assert hits
    assert hits[0].document_id == "doc1"
    assert hits[0].source_gcs_uri == "gs://bucket/doc1.pdf"


def test_verify_fails_on_tampered_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    reader = QdrantReader(settings)
    monkeypatch.setattr(
        reader,
        "_fetch_local",
        lambda: (True, DIM, _stamp(settings, fingerprint="deadbeefdeadbeef")),
    )

    with pytest.raises(VectorstoreContractError):
        asyncio.run(reader.verify_contract())


def test_verify_fails_when_collection_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    reader = QdrantReader(settings)
    monkeypatch.setattr(reader, "_fetch_local", lambda: (False, None, _stamp(settings)))

    with pytest.raises(VectorstoreContractError):
        asyncio.run(reader.verify_contract())
