"""Qdrant deployment `in_process` — embedded (không url), SYNC + to_thread.

Dùng khi `config.url` rỗng → chạy thẳng trong tiến trình qua `QdrantClient` local
(`:memory:` mặc định, hoặc `path=...` để persist). API local là SYNC nên mọi op bọc
`asyncio.to_thread` để interface ngoài vẫn async thuần, không chặn event loop.
"""

from __future__ import annotations

import asyncio
from typing import Sequence

from core_engine.vectorstore.providers.qdrant.base import QdrantBase, point_id

from qdrant_client import QdrantClient

from app.domain.repositories.vector_repository import SearchResult

from core_engine.vectorstore.config import VectorStoreConfig
from core_engine.vectorstore.store import VectorStore
from core_engine.vectorstore.types import VectorRecord


class QdrantInProcessProvider(QdrantBase):
    def __init__(self, config: VectorStoreConfig | None = None):
        super().__init__(config)
        options = dict(self.config.options)
        # Không khai báo location/path -> embedded RAM (:memory:).
        if "location" not in options and "path" not in options:
            options["location"] = ":memory:"
        self._client = QdrantClient(**options)
        self._ready = False
        self._lock = asyncio.Lock()
        # QdrantClient local (:memory:/path) KHÔNG thread-safe; serialize mọi op
        # (chạy qua to_thread) để concurrent ingest/search không đụng numpy index.
        self._op_lock = asyncio.Lock()

    async def _ensure(self) -> None:
        if self._ready:
            return
        async with self._lock:
            if self._ready:
                return
            exists = await asyncio.to_thread(self._client.collection_exists, self._collection)
            if not exists:
                await asyncio.to_thread(
                    self._client.create_collection,
                    collection_name=self._collection,
                    vectors_config=self._vectors_config(),
                )
            self._ready = True

    async def insert_many(self, records: Sequence[VectorRecord]) -> None:
        await self._ensure()
        record_list = list(records)
        if not record_list:
            return
        async with self._op_lock:
            points = await asyncio.to_thread(
                self._client.retrieve,
                collection_name=self._collection,
                ids=[point_id(r.chunk_id) for r in record_list],
                with_payload=True,
                with_vectors=False,
            )
            existing = self._existing_from_points(points)
            if existing:
                raise ValueError(
                    f"Chunk id da ton tai, insert khong duoc overwrite: {sorted(existing)[0]}"
                )
            await asyncio.to_thread(
                self._client.upsert,
                collection_name=self._collection,
                points=[self._point(r) for r in record_list],
            )

    async def upsert_many(self, records: Sequence[VectorRecord]) -> None:
        await self._ensure()
        record_list = list(records)
        if record_list:
            async with self._op_lock:
                await asyncio.to_thread(
                    self._client.upsert,
                    collection_name=self._collection,
                    points=[self._point(r) for r in record_list],
                )

    async def search(
        self,
        vector: Sequence[float],
        query_text: str,
        top_k: int = 20,
    ) -> list[SearchResult]:
        await self._ensure()
        async with self._op_lock:
            res = await asyncio.to_thread(
                self._client.query_points,
                collection_name=self._collection,
                query=list(vector),
                limit=top_k,
                with_payload=True,
            )
        return [self._to_result(point) for point in res.points]

    async def list_chunk_ids_by_document(self, document_id: str) -> list[str]:
        await self._ensure()
        async with self._op_lock:
            res = await asyncio.to_thread(
                self._client.scroll,
                collection_name=self._collection,
                scroll_filter=self._document_filter(document_id),
                with_payload=True,
                with_vectors=False,
                limit=10000,
            )
        points = res[0] if isinstance(res, tuple) else res
        return sorted(self._existing_from_points(points))

    async def delete_many(self, chunk_ids: Sequence[str]) -> None:
        await self._ensure()
        ids = list(chunk_ids)
        if ids:
            async with self._op_lock:
                await asyncio.to_thread(
                    self._client.delete,
                    collection_name=self._collection,
                    points_selector=self._ids_selector(ids),
                )

    async def delete_by_document(self, document_id: str) -> None:
        await self._ensure()
        async with self._op_lock:
            await asyncio.to_thread(
                self._client.delete,
                collection_name=self._collection,
                points_selector=self._delete_by_document_selector(document_id),
            )


class QdrantInProcessRepository(VectorStore):
    def __init__(self, config: VectorStoreConfig | None = None):
        provider = QdrantInProcessProvider(config)
        super().__init__(provider, provider.config)
