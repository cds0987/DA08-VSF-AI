"""Milvus deployment `remote` — service riêng (có url), ASYNC THUẦN.

Dùng khi `config.url` có giá trị → Milvus server/cluster qua `AsyncMilvusClient`
(`uri=url`, `token=api_key`). Async-native nên KHÔNG cần to_thread.
"""

from __future__ import annotations

import asyncio
from typing import Sequence

from haystack_interface.vectorstore.providers.milvus.base import PK, MilvusBase

try:
    from pymilvus import AsyncMilvusClient
except (ModuleNotFoundError, ImportError) as e:
    raise ModuleNotFoundError(
        "Provider 'milvus' remote can pymilvus>=2.5 (AsyncMilvusClient). "
        "Cai: pip install 'pymilvus>=2.5'"
    ) from e

from app.domain.repositories.vector_repository import SearchResult

from haystack_interface.vectorstore.config import VectorStoreConfig
from haystack_interface.vectorstore.store import VectorStore
from haystack_interface.vectorstore.types import VectorRecord


class MilvusRemoteProvider(MilvusBase):
    def __init__(self, config: VectorStoreConfig | None = None):
        super().__init__(config)
        options = dict(self.config.options)
        kwargs = {"uri": self.config.url}
        if self.config.api_key:
            kwargs["token"] = self.config.api_key
        kwargs.update(options)
        self._client = AsyncMilvusClient(**kwargs)
        self._ready = False
        self._lock = asyncio.Lock()

    async def _ensure(self) -> None:
        if self._ready:
            return
        async with self._lock:
            if self._ready:
                return
            if not await self._client.has_collection(self.collection_name):
                await self._client.create_collection(**self._create_kwargs())
            await self._client.load_collection(self.collection_name)
            self._ready = True

    async def insert_many(self, records: Sequence[VectorRecord]) -> None:
        await self._ensure()
        record_list = list(records)
        if not record_list:
            return
        existing = await self._client.get(
            collection_name=self.collection_name, ids=[r.chunk_id for r in record_list]
        )
        dup = self._dup_id(existing)
        if dup:
            raise ValueError(f"Chunk id da ton tai, insert khong duoc overwrite: {dup}")
        await self._client.insert(
            collection_name=self.collection_name, data=[self._row(r) for r in record_list]
        )

    async def upsert_many(self, records: Sequence[VectorRecord]) -> None:
        await self._ensure()
        record_list = list(records)
        if record_list:
            await self._client.upsert(
                collection_name=self.collection_name,
                data=[self._row(r) for r in record_list],
            )

    async def search(
        self,
        vector: Sequence[float],
        query_text: str,
        top_k: int = 20,
    ) -> list[SearchResult]:
        await self._ensure()
        res = await self._client.search(**self._search_kwargs(vector, top_k))
        return self._assemble(res[0] if res else [], top_k)

    async def list_chunk_ids_by_document(self, document_id: str) -> list[str]:
        await self._ensure()
        rows = await self._client.query(
            collection_name=self.collection_name,
            filter=self._doc_filter(document_id),
            output_fields=[PK],
        )
        return sorted(row.get(PK) for row in (rows or []) if row.get(PK))

    async def delete_many(self, chunk_ids: Sequence[str]) -> None:
        await self._ensure()
        ids = list(chunk_ids)
        if ids:
            await self._client.delete(collection_name=self.collection_name, ids=ids)

    async def delete_by_document(self, document_id: str) -> None:
        await self._ensure()
        await self._client.delete(
            collection_name=self.collection_name, filter=self._doc_filter(document_id)
        )


class MilvusRemoteRepository(VectorStore):
    def __init__(self, config: VectorStoreConfig | None = None):
        provider = MilvusRemoteProvider(config)
        super().__init__(provider, provider.config)
