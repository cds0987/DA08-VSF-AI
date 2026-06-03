"""ChromaDB deployment `remote` — service riêng (có url), ASYNC THUẦN.

Dùng khi `config.url` có giá trị → Chroma server qua `AsyncHttpClient`. Lưu ý:
`chromadb.AsyncHttpClient(...)` là coroutine PHẢI await để lấy client, nên client +
collection được khởi tạo LAZY trong `_ensure()` (không thể await trong __init__).
"""

from __future__ import annotations

import asyncio
from typing import Sequence
from urllib.parse import urlparse

from haystack_interface.vectorstore.providers.chromadb.base import (
    COLLECTION_METADATA,
    ChromaBase,
)

try:
    import chromadb
except ModuleNotFoundError as e:
    raise ModuleNotFoundError(
        "Provider 'chromadb' can chromadb. Cai: pip install chromadb"
    ) from e

from app.domain.repositories.vector_repository import SearchResult

from haystack_interface.vectorstore.config import VectorStoreConfig
from haystack_interface.vectorstore.store import VectorStore
from haystack_interface.vectorstore.types import VectorRecord


class ChromaRemoteProvider(ChromaBase):
    def __init__(self, config: VectorStoreConfig | None = None):
        super().__init__(config)
        self._collection = None
        self._lock = asyncio.Lock()

    async def _ensure(self):
        if self._collection is not None:
            return self._collection
        async with self._lock:
            if self._collection is not None:
                return self._collection
            options = dict(self.config.options)
            parsed = urlparse(self.config.url)
            host = options.pop("host", None) or parsed.hostname or self.config.url
            port = options.pop("port", None) or parsed.port or 8000
            headers = options.pop("headers", None)
            if self.config.api_key and headers is None:
                headers = {"Authorization": f"Bearer {self.config.api_key}"}
            client = await chromadb.AsyncHttpClient(
                host=host, port=int(port), headers=headers, **options
            )
            self._collection = await client.get_or_create_collection(
                name=self.collection_name, metadata=COLLECTION_METADATA
            )
            return self._collection

    async def insert_many(self, records: Sequence[VectorRecord]) -> None:
        record_list = list(records)
        if not record_list:
            return
        collection = await self._ensure()
        existing = await collection.get(ids=[r.chunk_id for r in record_list], include=[])
        dup = self._dup_id(existing)
        if dup:
            raise ValueError(f"Chunk id da ton tai, insert khong duoc overwrite: {dup}")
        await collection.add(**self._add_args(record_list))

    async def upsert_many(self, records: Sequence[VectorRecord]) -> None:
        record_list = list(records)
        if record_list:
            collection = await self._ensure()
            await collection.upsert(**self._add_args(record_list))

    async def search(
        self,
        vector: Sequence[float],
        query_text: str,
        top_k: int = 20,
    ) -> list[SearchResult]:
        collection = await self._ensure()
        res = await collection.query(
            query_embeddings=[list(vector)],
            n_results=top_k,
            include=["metadatas", "distances", "documents"],
        )
        return self._assemble(res, top_k)

    async def list_chunk_ids_by_document(self, document_id: str) -> list[str]:
        collection = await self._ensure()
        existing = await collection.get(where={"document_id": document_id}, include=[])
        return sorted(self._ids(existing))

    async def delete_many(self, chunk_ids: Sequence[str]) -> None:
        ids = list(chunk_ids)
        if ids:
            collection = await self._ensure()
            await collection.delete(ids=ids)

    async def delete_by_document(self, document_id: str) -> None:
        collection = await self._ensure()
        await collection.delete(where={"document_id": document_id})


class ChromaRemoteRepository(VectorStore):
    def __init__(self, config: VectorStoreConfig | None = None):
        provider = ChromaRemoteProvider(config)
        super().__init__(provider, provider.config)
