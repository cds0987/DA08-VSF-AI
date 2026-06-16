"""Reader Qdrant — BẢN RIÊNG mcp (chỉ ĐỌC; rag-worker là bên ghi).

Ghép với rag-worker CHỈ qua Qdrant. point_id (uuid5) + index_id + payload keys
phải khớp đúng cái rag-worker ghi, nếu không sẽ đọc nhầm/đọc rỗng.
"""

from __future__ import annotations

import asyncio
import binascii
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, List, Sequence

from app.core.connection import build_remote_client_kwargs
from app.core.config import McpSettings
from app.core.contract import check_stamp, meta_collection_name

_QDRANT_NS = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_QDRANT_NS, chunk_id))


@dataclass
class SearchHit:
    chunk_id: str = ""
    document_id: str = ""
    document_name: str = ""
    caption: str = ""
    child_text: str = ""
    parent_text: str = ""
    heading_path: List[str] = field(default_factory=list)
    score: float = 0.0
    page_number: int | None = None
    source_gcs_uri: str = ""
    markdown_gcs_uri: str = ""


def _to_hit(payload: dict, score: float) -> SearchHit:
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


def _vector_size(info: object) -> int | None:
    params = getattr(getattr(info, "config", None), "params", None)
    vectors = getattr(params, "vectors", None)
    if vectors is None:
        return None
    if hasattr(vectors, "size"):  # unnamed vector (old schema)
        return int(vectors.size)
    if isinstance(vectors, dict):
        # Named vectors: "dense" is the primary dense vector
        dense = vectors.get("dense")
        if dense is not None:
            size = getattr(dense, "size", None)
            return int(size) if size is not None else None
        # Single-entry fallback (any non-sparse named vector)
        if len(vectors) == 1:
            only = next(iter(vectors.values()))
            size = getattr(only, "size", None)
            return int(size) if size is not None else None
    return None


class QdrantReader:
    def __init__(self, settings: McpSettings) -> None:
        self._settings = settings
        self._contract = settings.contract()
        self._index = self._contract.index_id
        self._meta = meta_collection_name(settings.collection)
        self._stamp_id = point_id(f"__contract__::{self._index}")
        self._client = None

    # --- client helpers ---------------------------------------------------
    def _remote_client(self):
        if self._client is None:
            from qdrant_client import AsyncQdrantClient

            self._client = AsyncQdrantClient(**build_remote_client_kwargs(self._settings))
        return self._client

    def _local_client(self):
        from qdrant_client import QdrantClient

        options = dict(self._settings.options)
        if "location" not in options and "path" not in options:
            options["location"] = ":memory:"
        return QdrantClient(**options)

    async def aclose(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            await client.close()

    @staticmethod
    def _build_filter(document_ids: Sequence[str] | None):
        from qdrant_client import models

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
                    match=models.MatchAny(any=[str(document_id) for document_id in document_ids]),
                )
            ]
        )

    # --- contract verify (fail-closed) ------------------------------------
    async def verify_contract(self, *, expect_data_collection: bool = True):
        if self._settings.provider != "qdrant":
            return self._contract
        if self._settings.deployment == "remote":
            data_exists, size, stamp = await self._fetch_remote()
        else:
            data_exists, size, stamp = await asyncio.to_thread(self._fetch_local)
        self._assert(data_exists, size, stamp, expect_data_collection)
        return self._contract

    def _assert(self, data_exists, vector_size, stamp, expect_data_collection) -> None:
        from app.core.contract import VectorstoreContractError

        if expect_data_collection:
            if not data_exists:
                raise VectorstoreContractError(
                    f"Collection dữ liệu {self._index} chưa tồn tại trên Qdrant. "
                    "Producer (rag-worker) chưa ingest, hoặc mcp dùng model/dim khác."
                )
            if vector_size is not None and vector_size != self._contract.dimension:
                raise VectorstoreContractError(
                    f"Vector size lệch cho {self._index}: store={vector_size} "
                    f"vs contract={self._contract.dimension}. Đổi dimension là migration."
                )
        check_stamp(stamp, self._contract)

    async def _fetch_remote(self):
        client = self._remote_client()
        data_exists = await client.collection_exists(self._index)
        size = _vector_size(await client.get_collection(self._index)) if data_exists else None
        stamp = None
        if await client.collection_exists(self._meta):
            records = await client.retrieve(
                collection_name=self._meta, ids=[self._stamp_id], with_payload=True
            )
            if records:
                stamp = records[0].payload
        return data_exists, size, stamp

    def _fetch_local(self):
        client = self._local_client()
        try:
            data_exists = client.collection_exists(self._index)
            size = _vector_size(client.get_collection(self._index)) if data_exists else None
            stamp = None
            if client.collection_exists(self._meta):
                records = client.retrieve(
                    collection_name=self._meta, ids=[self._stamp_id], with_payload=True
                )
                if records:
                    stamp = records[0].payload
            return data_exists, size, stamp
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    # --- search -----------------------------------------------------------
    async def search(
        self,
        vector: Sequence[float],
        query_text: str,
        top_k: int,
        document_ids: Sequence[str] | None = None,
    ) -> List[SearchHit]:
        if self._settings.deployment == "remote":
            return await self._search_remote(vector, query_text, top_k, document_ids=document_ids)
        return await asyncio.to_thread(self._search_local, vector, query_text, top_k, document_ids)

    async def _search_remote(
        self,
        vector: Sequence[float],
        query_text: str,
        top_k: int,
        document_ids: Sequence[str] | None = None,
    ) -> List[SearchHit]:
        from qdrant_client import models

        client = self._remote_client()
        doc_filter = self._build_filter(document_ids)
        sparse_idx, sparse_val = _sparse_encode(query_text)
        res = await client.query_points(
            collection_name=self._index,
            prefetch=[
                models.Prefetch(
                    query=list(vector),
                    using="dense",
                    limit=top_k,
                    filter=doc_filter,
                ),
                models.Prefetch(
                    query=models.SparseVector(indices=sparse_idx, values=sparse_val),
                    using="sparse",
                    limit=top_k,
                    filter=doc_filter,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=top_k,
            with_payload=True,
        )
        return [_to_hit(p.payload, p.score) for p in res.points]

    def _search_local(
        self,
        vector: Sequence[float],
        query_text: str,
        top_k: int,
        document_ids: Sequence[str] | None = None,
    ) -> List[SearchHit]:
        from qdrant_client import models

        client = self._local_client()
        try:
            doc_filter = self._build_filter(document_ids)
            sparse_idx, sparse_val = _sparse_encode(query_text)
            res = client.query_points(
                collection_name=self._index,
                prefetch=[
                    models.Prefetch(
                        query=list(vector),
                        using="dense",
                        limit=top_k,
                        filter=doc_filter,
                    ),
                    models.Prefetch(
                        query=models.SparseVector(indices=sparse_idx, values=sparse_val),
                        using="sparse",
                        limit=top_k,
                        filter=doc_filter,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=top_k,
                with_payload=True,
            )
            return [_to_hit(p.payload, p.score) for p in res.points]
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()
