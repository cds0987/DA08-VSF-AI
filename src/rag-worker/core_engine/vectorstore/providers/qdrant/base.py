"""Phần dùng chung cho hai deployment của provider `qdrant`.

`remote.py` (async thuần, AsyncQdrantClient) và `inprocess.py` (sync + to_thread,
QdrantClient embedded) chia sẻ: mapping record→point, access pre-filter, map kết quả.
Chỉ KHÁC nhau ở cơ chế gọi client (await thuần vs to_thread) nên phần đó nằm ở từng file.
"""

from __future__ import annotations

import binascii
import re
import uuid
from collections import Counter
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


def _sparse_encode(text: str) -> tuple[list[int], list[float]]:
    tokens = re.findall(r"\w+", text.lower())
    if not tokens:
        return [], []
    counts = Counter(tokens)
    result: dict[int, float] = {}
    for token, count in counts.items():
        idx = binascii.crc32(token.encode()) % (1 << 16)
        result[idx] = result.get(idx, 0) + count
    total = sum(result.values())
    indices = sorted(result)
    values = [result[i] / total for i in indices]
    return indices, values


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
        if record.sparse_indices:
            vector: object = {
                "dense": list(record.vector),
                "sparse": models.SparseVector(
                    indices=record.sparse_indices,
                    values=record.sparse_values,
                ),
            }
        else:
            vector = list(record.vector)
        return models.PointStruct(
            id=point_id(record.chunk_id),
            vector=vector,
            payload={**record.payload, "chunk_id": record.chunk_id},
        )

    def _collection_create_kwargs(self) -> dict:
        return {
            "vectors_config": {
                "dense": models.VectorParams(
                    size=self.config.dimension, distance=models.Distance.COSINE
                )
            },
            "sparse_vectors_config": {"sparse": models.SparseVectorParams()},
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
