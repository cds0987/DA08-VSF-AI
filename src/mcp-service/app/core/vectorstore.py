"""Reader Qdrant — BẢN RIÊNG mcp (chỉ ĐỌC; rag-worker là bên ghi).

Ghép với rag-worker CHỈ qua Qdrant. point_id (uuid5) + index_id + payload keys
phải khớp đúng cái rag-worker ghi, nếu không sẽ đọc nhầm/đọc rỗng.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, List, Sequence
from urllib.parse import urlparse, urlunparse

from app.core.config import McpSettings
from app.core.contract import check_stamp, meta_collection_name

_QDRANT_NS = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")


def _normalize_remote_url(url: str) -> str:
    """Qdrant Cloud Run expose HTTPS qua 443; URL không port -> qdrant-client mặc
    định rớt về 6333 (sai). Thêm :443 cho URL https thiếu port (idempotent)."""
    if not url:
        return url
    parsed = urlparse(url)
    if not parsed.scheme or parsed.port is not None or not parsed.hostname:
        return url
    if parsed.scheme == "https":
        return urlunparse(parsed._replace(netloc=f"{parsed.hostname}:443"))
    return url


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_QDRANT_NS, chunk_id))


@dataclass
class SearchHit:
    chunk_id: str = ""
    document_id: str = ""
    document_name: str = ""
    caption: str = ""
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
        parent_text=str(m.get("parent_text", "")),
        heading_path=list(m.get("heading_path", []) or []),
        score=float(score) if score is not None else 0.0,
        page_number=m.get("page_number"),
        source_gcs_uri=str(m.get("source_uri", "")),
        markdown_gcs_uri=str(m.get("artifact_uri", "")),
    )


def _vector_size(info: object) -> int | None:
    params = getattr(getattr(info, "config", None), "params", None)
    vectors = getattr(params, "vectors", None)
    if vectors is None:
        return None
    if hasattr(vectors, "size"):
        return int(vectors.size)
    if isinstance(vectors, dict) and len(vectors) == 1:
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
            import os

            from qdrant_client import AsyncQdrantClient

            options = dict(self._settings.options)
            # Qdrant Cloud Run (region xa + cold start) -> connect/TLS có thể vượt
            # timeout mặc định httpx. Nới timeout (env override) cho verify/search.
            options.setdefault("timeout", int(os.getenv("QDRANT_TIMEOUT", "30")))
            self._client = AsyncQdrantClient(
                url=_normalize_remote_url(self._settings.url) or None,
                api_key=self._settings.api_key or None,
                **options,
            )
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
        if not document_ids:
            return None
        from qdrant_client import models

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
            return await self._search_remote(vector, top_k, document_ids=document_ids)
        return await asyncio.to_thread(self._search_local, vector, top_k, document_ids)

    async def _search_remote(
        self, vector: Sequence[float], top_k: int, document_ids: Sequence[str] | None = None
    ) -> List[SearchHit]:
        client = self._remote_client()
        res = await client.query_points(
            collection_name=self._index,
            query=list(vector),
            limit=top_k,
            with_payload=True,
            query_filter=self._build_filter(document_ids),
        )
        return [_to_hit(p.payload, p.score) for p in res.points]

    def _search_local(
        self, vector: Sequence[float], top_k: int, document_ids: Sequence[str] | None = None
    ) -> List[SearchHit]:
        client = self._local_client()
        try:
            res = client.query_points(
                collection_name=self._index,
                query=list(vector),
                limit=top_k,
                with_payload=True,
                query_filter=self._build_filter(document_ids),
            )
            return [_to_hit(p.payload, p.score) for p in res.points]
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()
