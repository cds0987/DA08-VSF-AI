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
from core_engine.vectorstore.types import SearchHit, VectorRecord

_QDRANT_NS = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_QDRANT_NS, chunk_id))


def is_qdrant_collection_missing_error(exc: BaseException) -> bool:
    """404 từ op collection-scoped (upsert/insert/search/delete/list) = collection THIẾU ->
    caller recreate + retry (idempotent).

    KHÔNG match phrasing cụ thể: Qdrant đổi message giữa version ("Collection ... doesn't
    exist!" vs "Not found: Collection ... not found") -> match từng chữ là GIÒN. Gốc 2026-06-27:
    reingest sau khi xoá collection -> 404 "Not Found" KHÔNG khớp "doesn't exist" -> không
    recover -> 105 doc permanent-fail. Dựa STATUS 404 (tín hiệu semantic, không hardcode chữ):
    recreate idempotent + retry BOUNDED 1 lần -> an toàn cả khi 404 vì lý do khác (404 lại -> raise)."""
    return isinstance(exc, UnexpectedResponse) and getattr(exc, "status_code", None) == 404


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
            if not idx:  # engine chưa điền -> encode BM25 document từ bm25_text
                from core_engine.vectorstore.sparse import sparse_encode_document
                idx, val = sparse_encode_document(str(record.payload.get("bm25_text", "")))
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
                # modifier=IDF: Qdrant tự tính IDF từ corpus phía server -> BM25 thật
                # (value document = TF bão hoà; value query = TF thô; score = Σ IDF·doc·query).
                "sparse_vectors_config": {
                    "sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)
                },
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

    # --- search (query-side, port từ mcp QdrantReader) -------------------- #
    @staticmethod
    def _access_filter(document_ids: Sequence[str] | None) -> "models.Filter":
        """ACL filter trên document_id — ĐỐI XỨNG mcp _build_filter.

        CRITICAL: document_ids None/rỗng -> match ["__no_access__"] (= KHÔNG có doc
        nào) -> kết quả RỖNG. Caller truyền danh sách doc-id ACL cho phép; rỗng nghĩa
        là không có quyền truy cập, KHÔNG phải "tìm tất cả". Giữ nguyên hành vi này."""
        if not document_ids:
            return models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchAny(any=["__no_access__"]),
                    )
                ]
            )
        return models.Filter(
            must=[
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchAny(any=[str(d) for d in document_ids]),
                )
            ]
        )

    @staticmethod
    def _collection_mode(info) -> str:
        """'hybrid' nếu collection có sparse vectors config; ngược lại 'dense'.

        ĐỐI XỨNG mcp QdrantReader._collection_mode: chỉ phân biệt theo SỰ TỒN TẠI của
        sparse. Collection hybrid (mới) -> prefetch dense+sparse fusion (named vectors).
        Collection cũ (unnamed, prod chưa migrate) -> dense KHÔNG truyền `using` (verify
        prod: using='dense' trên unnamed -> 400 -> 0 sources)."""
        try:
            sparse = getattr(info.config.params, "sparse_vectors", None)
        except Exception:  # noqa: BLE001 — info lạ -> an toàn: dense không-using
            return "dense"
        return "hybrid" if sparse else "dense"

    def _hybrid_query_kwargs(self, vector, query_text, top_k, doc_filter) -> dict:
        """kwargs cho query_points chế độ hybrid (dense+sparse RRF fusion)."""
        from core_engine.vectorstore.sparse import sparse_encode_query

        sparse_idx, sparse_val = sparse_encode_query(query_text)
        return {
            "collection_name": self._collection,
            "prefetch": [
                models.Prefetch(
                    query=list(vector), using="dense", limit=top_k, filter=doc_filter
                ),
                models.Prefetch(
                    query=models.SparseVector(indices=sparse_idx, values=sparse_val),
                    using="sparse",
                    limit=top_k,
                    filter=doc_filter,
                ),
            ],
            "query": models.FusionQuery(fusion=models.Fusion.RRF),
            "limit": top_k,
            "with_payload": True,
        }

    def _dense_query_kwargs(self, vector, top_k, doc_filter) -> dict:
        """kwargs cho query_points chế độ dense trần (collection cũ unnamed)."""
        return {
            "collection_name": self._collection,
            "query": list(vector),
            "query_filter": doc_filter,
            "limit": top_k,
            "with_payload": True,
        }

    @staticmethod
    def _to_search_hit(payload: dict | None, score: float | None) -> SearchHit:
        """payload Qdrant -> SearchHit. ĐỐI XỨNG mcp _to_hit (1-nguồn-sự-thật)."""
        m = payload or {}
        return SearchHit(
            chunk_id=str(m.get("chunk_id", "")),
            document_id=str(m.get("document_id", "")),
            document_name=str(m.get("document_name", "")),
            caption=str(m.get("caption", m.get("child_text", ""))),
            child_text=str(m.get("child_text", "")),
            parent_text=str(m.get("parent_text", "")),
            heading_path=list(m.get("heading_path", []) or []),
            score=float(score) if score is not None else 0.0,
            page_number=m.get("page_number"),
            source_gcs_uri=str(m.get("source_uri", "")),
            markdown_gcs_uri=str(m.get("artifact_uri", "")),
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
