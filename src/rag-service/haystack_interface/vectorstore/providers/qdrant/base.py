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
except ModuleNotFoundError as e:
    raise ModuleNotFoundError(
        "Provider 'qdrant' can qdrant-client. Cai: pip install qdrant-client"
    ) from e

from app.domain.repositories.vector_repository import SearchResult, UserContext

from haystack_interface.access import (
    DEPARTMENT_FIELD,
    DEPT_SCOPED,
    OPEN_CLASSIFICATIONS,
    USER_FIELD,
    USER_SCOPED,
)
from haystack_interface.vectorstore.config import VectorStoreConfig
from haystack_interface.vectorstore.provider import VectorStoreProvider
from haystack_interface.vectorstore.types import VectorRecord

_QDRANT_NS = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_QDRANT_NS, chunk_id))


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
        return models.PointStruct(
            id=point_id(record.chunk_id),
            vector=list(record.vector),
            payload={**record.payload, "chunk_id": record.chunk_id},
        )

    @staticmethod
    def _access_filter(ctx: UserContext) -> "models.Filter | None":
        if ctx.user_role == "admin":
            return None
        return models.Filter(
            should=[
                models.FieldCondition(
                    key="classification",
                    match=models.MatchAny(any=list(OPEN_CLASSIFICATIONS)),
                ),
                models.Filter(
                    must=[
                        models.FieldCondition(
                            key="classification",
                            match=models.MatchValue(value=DEPT_SCOPED),
                        ),
                        models.FieldCondition(
                            key=DEPARTMENT_FIELD,
                            match=models.MatchValue(value=ctx.user_department),
                        ),
                    ]
                ),
                models.Filter(
                    must=[
                        models.FieldCondition(
                            key="classification",
                            match=models.MatchValue(value=USER_SCOPED),
                        ),
                        models.FieldCondition(
                            key=USER_FIELD,
                            match=models.MatchValue(value=ctx.user_id),
                        ),
                    ]
                ),
            ]
        )

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

    @staticmethod
    def _ids_selector(chunk_ids: Sequence[str]) -> "models.PointIdsList":
        return models.PointIdsList(points=[point_id(c) for c in chunk_ids])

    @staticmethod
    def _to_result(point) -> SearchResult:
        m = point.payload or {}
        return SearchResult(
            chunk_id=m.get("chunk_id", str(point.id)),
            parent_id=m.get("parent_id", ""),
            document_id=m.get("document_id", ""),
            document_name=m.get("document_name", ""),
            file_type=m.get("file_type", ""),
            page_number=int(m.get("page_number", 0)),
            section_title=m.get("section_title", ""),
            child_text=m.get("child_text", ""),
            parent_text=m.get("parent_text", ""),
            score=float(point.score) if point.score is not None else 0.0,
            rerank_score=float(m.get("rerank_score", 0.0)),
        )

    @staticmethod
    def _existing_from_points(points) -> set[str]:
        out: set[str] = set()
        for point in points:
            chunk_id = (point.payload or {}).get("chunk_id")
            if chunk_id:
                out.add(chunk_id)
        return out
