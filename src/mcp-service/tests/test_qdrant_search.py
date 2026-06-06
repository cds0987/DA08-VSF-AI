"""Qdrant reader contract tests without relying on local disk persistence."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

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
        lambda vector, top_k, document_ids=None: [
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


def test_build_filter_scopes_to_document_ids() -> None:
    scoped = QdrantReader._build_filter(["doc-a", "doc-b"])

    assert scoped is not None
    condition = scoped.must[0]
    assert condition.key == "document_id"
    assert list(condition.match.any) == ["doc-a", "doc-b"]


@pytest.mark.asyncio
async def test_remote_search_passes_document_filter_and_reuses_client(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    settings = McpSettings(**{**settings.__dict__, "url": "http://qdrant:6333"})
    reader = QdrantReader(settings)
    recorded_filters: list[object] = []

    class FakeClient:
        async def query_points(self, **kwargs):
            recorded_filters.append(kwargs.get("query_filter"))
            payload = {
                "chunk_id": "chunk-1",
                "document_id": "doc-a",
                "document_name": "Doc A",
                "caption": "Leave policy",
                "parent_text": "Annual leave is 12 days.",
            }
            return SimpleNamespace(points=[SimpleNamespace(payload=payload, score=0.9)])

        async def close(self):
            return None

    fake_client = FakeClient()
    monkeypatch.setattr(reader, "_client", fake_client)

    first = await reader.search([0.1, 0.2], "leave", top_k=5, document_ids=["doc-a"])
    second = await reader.search([0.1, 0.2], "leave", top_k=5, document_ids=["doc-a"])

    assert [hit.document_id for hit in first] == ["doc-a"]
    assert [hit.document_id for hit in second] == ["doc-a"]
    assert len(recorded_filters) == 2
    assert recorded_filters[0] is not None
    assert recorded_filters[1] is not None
