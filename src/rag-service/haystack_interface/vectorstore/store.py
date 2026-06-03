from __future__ import annotations

from typing import Mapping, Sequence

from app.domain.repositories.vector_repository import SearchResult, VectorRepository

from haystack_interface.vectorstore.config import VectorStoreConfig
from haystack_interface.vectorstore.provider import VectorStoreProvider
from haystack_interface.vectorstore.types import VectorRecord


class VectorStore(VectorRepository):
    def __init__(self, provider: VectorStoreProvider, config: VectorStoreConfig | None = None):
        self._provider = provider
        self._config = config or provider.config

    @property
    def config(self) -> VectorStoreConfig:
        return self._config

    @property
    def provider(self) -> VectorStoreProvider:
        return self._provider

    async def insert(self, chunk_id: str, vector: Sequence[float], payload: Mapping[str, object]) -> None:
        await self.insert_many([VectorRecord(chunk_id=chunk_id, vector=vector, payload=payload)])

    async def insert_many(self, records: Sequence[VectorRecord]) -> None:
        await self._provider.insert_many(records)

    async def upsert(self, chunk_id: str, vector: list[float], payload: dict) -> None:
        await self.upsert_many([VectorRecord(chunk_id=chunk_id, vector=vector, payload=payload)])

    async def upsert_many(self, records: Sequence[VectorRecord]) -> None:
        await self._provider.upsert_many(records)

    async def search(
        self,
        vector: Sequence[float],
        query_text: str,
        top_k: int = 20,
    ) -> list[SearchResult]:
        return await self._provider.search(vector, query_text, top_k=top_k)

    async def hybrid_search(
        self,
        vector: list[float],
        query_text: str,
        top_k: int = 20,
    ) -> list[SearchResult]:
        return await self.search(vector, query_text, top_k=top_k)

    async def list_chunk_ids_by_document(self, document_id: str) -> list[str]:
        return await self._provider.list_chunk_ids_by_document(document_id)

    async def delete(self, chunk_id: str) -> None:
        await self.delete_many([chunk_id])

    async def delete_many(self, chunk_ids: Sequence[str]) -> None:
        await self._provider.delete_many(chunk_ids)

    async def delete_by_document(self, document_id: str) -> None:
        await self._provider.delete_by_document(document_id)
