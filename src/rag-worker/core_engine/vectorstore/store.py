from __future__ import annotations

from typing import Mapping, Sequence

from core_engine.types import VectorRepository
from core_engine.vectorstore.config import VectorStoreConfig
from core_engine.vectorstore.provider import VectorStoreProvider
from core_engine.vectorstore.types import SearchHit, VectorRecord


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

    async def list_chunk_ids_by_document(self, document_id: str) -> list[str]:
        return await self._provider.list_chunk_ids_by_document(document_id)

    async def delete(self, chunk_id: str) -> None:
        await self.delete_many([chunk_id])

    async def delete_many(self, chunk_ids: Sequence[str]) -> None:
        await self._provider.delete_many(chunk_ids)

    async def delete_by_document(self, document_id: str) -> None:
        await self._provider.delete_by_document(document_id)

    async def search(
        self,
        *,
        query_vector: Sequence[float],
        query_text: str,
        top_k: int,
        document_ids: Sequence[str] | None,
    ) -> list[SearchHit]:
        """Query-side retrieval (port từ mcp). Provider phải implement `search`
        (qdrant có; chromadb/milvus chưa cần -> AttributeError rõ ràng nếu gọi nhầm)."""
        search = getattr(self._provider, "search", None)
        if search is None:
            raise NotImplementedError(
                f"Provider {type(self._provider).__name__} không hỗ trợ search()"
            )
        return await search(
            query_vector=query_vector,
            query_text=query_text,
            top_k=top_k,
            document_ids=document_ids,
        )
