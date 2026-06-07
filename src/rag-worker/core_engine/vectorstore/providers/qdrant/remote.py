"""Qdrant deployment `remote` — service riêng (có url), ASYNC THUẦN.

Dùng khi `config.url` có giá trị (Qdrant Cloud hoặc self-hosted server). Client
`AsyncQdrantClient` là async-native nên KHÔNG cần to_thread.
"""

from __future__ import annotations

import asyncio
from typing import Sequence

from core_engine.vectorstore.providers.qdrant.base import QdrantBase, point_id

from qdrant_client import AsyncQdrantClient, models

from core_engine.vectorstore.config import VectorStoreConfig
from core_engine.vectorstore.store import VectorStore
from core_engine.vectorstore.types import VectorRecord


class QdrantRemoteProvider(QdrantBase):
    def __init__(self, config: VectorStoreConfig | None = None):
        super().__init__(config)
        options = dict(self.config.options)
        self._client = AsyncQdrantClient(
            url=self.config.url or None,
            api_key=self.config.api_key or None,
            **options,
        )
        self._ready = False
        self._lock = asyncio.Lock()

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

    async def insert_many(self, records: Sequence[VectorRecord]) -> None:
        await self._ensure()
        record_list = list(records)
        if not record_list:
            return
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

    async def upsert_many(self, records: Sequence[VectorRecord]) -> None:
        await self._ensure()
        record_list = list(records)
        if record_list:
            await self._client.upsert(
                collection_name=self._collection,
                points=[self._point(r) for r in record_list],
            )

    async def list_chunk_ids_by_document(self, document_id: str) -> list[str]:
        await self._ensure()
        res = await self._client.scroll(
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
            await self._client.delete(
                collection_name=self._collection,
                points_selector=self._ids_selector(ids),
            )

    async def delete_by_document(self, document_id: str) -> None:
        await self._ensure()
        await self._client.delete(
            collection_name=self._collection,
            points_selector=self._delete_by_document_selector(document_id),
        )


class QdrantRemoteRepository(VectorStore):
    def __init__(self, config: VectorStoreConfig | None = None):
        provider = QdrantRemoteProvider(config)
        super().__init__(provider, provider.config)
