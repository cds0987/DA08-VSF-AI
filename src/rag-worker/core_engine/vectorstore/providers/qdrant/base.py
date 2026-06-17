"""Phần dùng chung cho hai deployment của provider `qdrant`.

`remote.py` (async thuần, AsyncQdrantClient) và `inprocess.py` (sync + to_thread,
QdrantClient embedded) chia sẻ: mapping record→point, access pre-filter, map kết quả.
Chỉ KHÁC nhau ở cơ chế gọi client (await thuần vs to_thread) nên phần đó nằm ở từng file.
"""

from __future__ import annotations

import uuid
from typing import Sequence

try:
    from qdrant_client import models
    from qdrant_client.http.exceptions import UnexpectedResponse
except ModuleNotFoundError as e:
    raise ModuleNotFoundError(
        "Provider 'qdrant' can qdrant-client. Cai: pip install qdrant-client"
    ) from e

from core_engine.vectorstore.config import VectorStoreConfig
from core_engine.vectorstore.provider import VectorStoreProvider
from core_engine.vectorstore.types import VectorRecord

_QDRANT_NS = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_QDRANT_NS, chunk_id))


def is_qdrant_collection_missing_error(exc: BaseException) -> bool:
    if not isinstance(exc, UnexpectedResponse):
        return False
    if getattr(exc, "status_code", None) != 404:
        return False
    text = " ".join(
        str(part)
        for part in (
            getattr(exc, "reason_phrase", ""),
            getattr(exc, "content", ""),
            exc,
        )
        if part
    ).lower()
    return "collection" in text and ("doesn't exist" in text or "does not exist" in text)


class QdrantBase(VectorStoreProvider):
    """Phần thuần dữ liệu (không I/O) — hai deployment kế thừa rồi tự nối client."""

    def __init__(self, config: VectorStoreConfig | None = None):
        super().__init__(config or VectorStoreConfig(provider="qdrant"))
        self._collection = self.config.index_id()

    def _point(self, record: VectorRecord) -> "models.PointStruct":
        if len(record.vector) != self.config.dimension:
            raise ValueError(
                f"Sai dimension: vector={len(record.vector)} != index={self.config.dimension}. "
                "Doi dimension la migration (ingestion.md §8)."
            )
        payload = {**record.payload, "chunk_id": record.chunk_id}
        if getattr(self.config, "hybrid", False):
            # Named vector "dense" + "sparse" (khớp query mcp using=dense/sparse + RRF).
            idx, val = record.sparse_indices, record.sparse_values
            if not idx:  # engine chưa điền -> encode từ bm25_text (CÙNG hàm với mcp)
                from core_engine.vectorstore.sparse import sparse_encode
                idx, val = sparse_encode(str(record.payload.get("bm25_text", "")))
            return models.PointStruct(
                id=point_id(record.chunk_id),
                vector={
                    "dense": list(record.vector),
                    "sparse": models.SparseVector(indices=list(idx), values=list(val)),
                },
                payload=payload,
            )
        return models.PointStruct(
            id=point_id(record.chunk_id),
            vector=list(record.vector),
            payload=payload,
        )

    def _collection_create_kwargs(self) -> dict:
        if getattr(self.config, "hybrid", False):
            return {
                "vectors_config": {
                    "dense": models.VectorParams(
                        size=self.config.dimension, distance=models.Distance.COSINE
                    ),
                },
                "sparse_vectors_config": {"sparse": models.SparseVectorParams()},
            }
        return {
            "vectors_config": models.VectorParams(
                size=self.config.dimension, distance=models.Distance.COSINE
            ),
        }

    def _vectors_config(self) -> "models.VectorParams":
        return models.VectorParams(size=self.config.dimension, distance=models.Distance.COSINE)

    def _delete_by_document_selector(self, document_id: str) -> "models.FilterSelector":
        return models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=document_id),
                    )
                ]
            )
        )

    def _document_filter(self, document_id: str) -> "models.Filter":
        return models.Filter(
            must=[
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchValue(value=document_id),
                )
            ]
        )

    @staticmethod
    def _ids_selector(chunk_ids: Sequence[str]) -> "models.PointIdsList":
        return models.PointIdsList(points=[point_id(c) for c in chunk_ids])

    @staticmethod
    def _existing_from_points(points) -> set[str]:
        out: set[str] = set()
        for point in points:
            chunk_id = (point.payload or {}).get("chunk_id")
            if chunk_id:
                out.add(chunk_id)
        return out
