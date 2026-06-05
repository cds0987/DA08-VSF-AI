"""Roundtrip in-process Qdrant: giả lập producer (rag-worker) ghi data + dấu niêm,
rồi mcp verify_contract + search + rag_search. Negative: stamp lệch -> raise.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.config import McpSettings
from app.core.contract import VectorstoreContractError, meta_collection_name
from app.core.search import SearchService
from app.core.embedding import OfflineEmbedder
from app.core.rerank import NoopReranker
from app.core.text_utils import hash_embed
from app.core.vectorstore import QdrantReader, point_id

DIM = 256
DOC_TEXT = "Chính sách nghỉ phép thường niên 12 ngày cho nhân viên"
QUERY = "nghỉ phép thường niên"


def _settings(path: Path, *, model: str = "offline", dim: int = DIM) -> McpSettings:
    return McpSettings(
        provider="qdrant",
        collection="rag_chatbot",
        embed_model=model,
        dimension=dim,
        url="",
        api_key="",
        embed_base_url="",
        embed_api_key="",
        rerank_impl="none",
        top_k_candidates=20,
        rerank_top_k=3,
        rerank_threshold=0.0,
        options={"path": str(path)},
    )


def _seed_producer(path: Path, settings: McpSettings, *, fingerprint: str | None = None) -> None:
    """Mô phỏng rag-worker: ghi collection dữ liệu + dấu niêm vào meta collection."""
    from qdrant_client import QdrantClient, models

    contract = settings.contract()
    fp = fingerprint if fingerprint is not None else contract.fingerprint
    client = QdrantClient(path=str(path))
    try:
        # Data collection
        client.create_collection(
            contract.index_id,
            vectors_config=models.VectorParams(size=DIM, distance=models.Distance.COSINE),
        )
        client.upsert(
            contract.index_id,
            points=[
                models.PointStruct(
                    id=point_id("doc1::p0::c0"),
                    vector=hash_embed([DOC_TEXT], DIM)[0],
                    payload={
                        "chunk_id": "doc1::p0::c0",
                        "document_id": "doc1",
                        "document_name": "Sổ tay nhân viên",
                        "caption": "Nghỉ phép",
                        "parent_text": DOC_TEXT,
                        "heading_path": ["Phúc lợi"],
                        "page_number": 1,
                        "source_uri": "gs://bucket/doc1.pdf",
                        "artifact_uri": "gs://bucket/doc1.md",
                    },
                )
            ],
        )
        # Meta collection (dấu niêm)
        meta = meta_collection_name(settings.collection)
        client.create_collection(
            meta, vectors_config=models.VectorParams(size=1, distance=models.Distance.COSINE)
        )
        client.upsert(
            meta,
            points=[
                models.PointStruct(
                    id=point_id(f"__contract__::{contract.index_id}"),
                    vector=[1.0],
                    payload={
                        "kind": "__contract__",
                        "index_id": contract.index_id,
                        "fingerprint": fp,
                        "provider": contract.provider,
                        "collection": contract.collection,
                        "embed_model": contract.embed_model,
                        "dimension": contract.dimension,
                        "schema_version": contract.schema_version,
                        "written_by": "rag-worker",
                        "written_at": datetime.now(UTC).isoformat(),
                    },
                )
            ],
        )
    finally:
        client.close()


def test_verify_and_search_roundtrip(tmp_path: Path) -> None:
    store = tmp_path / "q"
    settings = _settings(store)
    _seed_producer(store, settings)

    reader = QdrantReader(settings)
    asyncio.run(reader.verify_contract())  # không raise

    service = SearchService(settings, OfflineEmbedder(DIM), reader, NoopReranker())
    hits = asyncio.run(service.rag_search(QUERY, document_ids=["doc1"], top_k=3))
    assert hits, "search phải trả ít nhất 1 hit"
    assert hits[0].document_id == "doc1"
    assert hits[0].source_gcs_uri == "gs://bucket/doc1.pdf"


def test_verify_fails_on_tampered_fingerprint(tmp_path: Path) -> None:
    store = tmp_path / "q"
    settings = _settings(store)
    _seed_producer(store, settings, fingerprint="deadbeefdeadbeef")  # stamp sai
    reader = QdrantReader(settings)
    with pytest.raises(VectorstoreContractError):
        asyncio.run(reader.verify_contract())


def test_verify_fails_when_collection_missing(tmp_path: Path) -> None:
    # Không seed gì -> data collection chưa tồn tại -> fail-closed.
    settings = _settings(tmp_path / "empty")
    reader = QdrantReader(settings)
    with pytest.raises(VectorstoreContractError):
        asyncio.run(reader.verify_contract())
