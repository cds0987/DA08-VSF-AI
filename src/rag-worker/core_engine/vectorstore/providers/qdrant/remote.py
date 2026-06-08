"""Qdrant deployment `remote` — service riêng (có url), ASYNC THUẦN.

Dùng khi `config.url` có giá trị (Qdrant Cloud hoặc self-hosted server). Client
`AsyncQdrantClient` là async-native nên KHÔNG cần to_thread.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from typing import Sequence

from core_engine.vectorstore.providers.qdrant.base import (
    QdrantBase,
    is_qdrant_collection_missing_error,
    point_id,
)

from qdrant_client import AsyncQdrantClient, models

from core_engine.vectorstore.config import VectorStoreConfig
from core_engine.vectorstore.store import VectorStore
from core_engine.vectorstore.types import VectorRecord


class QdrantRemoteProvider(QdrantBase):
    def __init__(self, config: VectorStoreConfig | None = None):
        super().__init__(config)
        self._client = AsyncQdrantClient(**self.config.remote_client_kwargs())
        self._ready = False
        self._lock = asyncio.Lock()
        self._upsert_batch = max(1, int(os.getenv("UPSERT_BATCH_SIZE", "256")))

    async def _ensure(self) -> None:
        if self._ready:
            return
        async with self._lock:
            if self._ready:
                return
            if not await self._client.collection_exists(self._collection):
                await self._client.create_collection(
                    collection_name=self._collection,
                    vectors_config=self._vectors_config(),
                )
                # Filter theo document_id (dedup scroll + delete + scoped search) yêu cầu
                # payload index keyword; Qdrant Cloud bật "indexing required for filtering"
                # nên thiếu index -> 400. Tạo ngay lúc tạo collection (idempotent).
                await self._client.create_payload_index(
                    collection_name=self._collection,
                    field_name="document_id",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
            self._ready = True

    async def _retry_on_missing_collection(
        self,
        op: Callable[[], Awaitable[object]],
    ) -> object:
        try:
            return await op()
        except Exception as exc:
            if not is_qdrant_collection_missing_error(exc):
                raise
            self._ready = False
            await self._ensure()
            return await op()

    async def insert_many(self, records: Sequence[VectorRecord]) -> None:
        record_list = list(records)
        if not record_list:
            return

        async def op() -> None:
            await self._ensure()
            points = await self._client.retrieve(
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
            await self._client.upsert(
                collection_name=self._collection,
                points=[self._point(r) for r in record_list],
            )

        await self._retry_on_missing_collection(op)

    async def upsert_many(self, records: Sequence[VectorRecord]) -> None:
        record_list = list(records)
        if not record_list:
            return
        points = [self._point(r) for r in record_list]

        async def op() -> None:
            await self._ensure()
            for index in range(0, len(points), self._upsert_batch):
                await self._client.upsert(
                    collection_name=self._collection,
                    points=points[index : index + self._upsert_batch],
                )

        await self._retry_on_missing_collection(op)

    async def list_chunk_ids_by_document(self, document_id: str) -> list[str]:
        async def op() -> list[str]:
            await self._ensure()
            chunk_ids: set[str] = set()
            offset = None
            while True:
                points, offset = await self._client.scroll(
                    collection_name=self._collection,
                    scroll_filter=self._document_filter(document_id),
                    with_payload=True,
                    with_vectors=False,
                    limit=1000,
                    offset=offset,
                )
                chunk_ids.update(self._existing_from_points(points))
                if offset is None:
                    break
            return sorted(chunk_ids)

        return await self._retry_on_missing_collection(op)

    async def delete_many(self, chunk_ids: Sequence[str]) -> None:
        ids = list(chunk_ids)
        if not ids:
            return

        async def op() -> None:
            await self._ensure()
            await self._client.delete(
                collection_name=self._collection,
                points_selector=self._ids_selector(ids),
            )

        await self._retry_on_missing_collection(op)

    async def delete_by_document(self, document_id: str) -> None:
        async def op() -> None:
            await self._ensure()
            await self._client.delete(
                collection_name=self._collection,
                points_selector=self._delete_by_document_selector(document_id),
            )

        await self._retry_on_missing_collection(op)


class QdrantRemoteRepository(VectorStore):
    def __init__(self, config: VectorStoreConfig | None = None):
        provider = QdrantRemoteProvider(config)
        super().__init__(provider, provider.config)
