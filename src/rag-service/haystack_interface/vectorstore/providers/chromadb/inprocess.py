"""ChromaDB deployment `in_process` — embedded (không url), SYNC + to_thread.

Dùng khi `config.url` rỗng → chạy thẳng trong tiến trình:
- mặc định `EphemeralClient` (RAM);
- có `options['path']` → `PersistentClient(path=...)` để persist trên đĩa.

Client embedded là SYNC nên mọi op bọc `asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio
from typing import Sequence

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


class ChromaInProcessProvider(ChromaBase):
    def __init__(self, config: VectorStoreConfig | None = None):
        super().__init__(config)
        options = dict(self.config.options)
        path = options.pop("path", None)
        if path:
            client = chromadb.PersistentClient(path=path, **options)
        else:
            client = chromadb.EphemeralClient(**options)
        self._collection = client.get_or_create_collection(
            name=self.collection_name, metadata=COLLECTION_METADATA
        )

    async def insert_many(self, records: Sequence[VectorRecord]) -> None:
        record_list = list(records)
        if not record_list:
            return
        existing = await asyncio.to_thread(
            self._collection.get, ids=[r.chunk_id for r in record_list], include=[]
        )
        dup = self._dup_id(existing)
        if dup:
            raise ValueError(f"Chunk id da ton tai, insert khong duoc overwrite: {dup}")
        args = self._add_args(record_list)
        await asyncio.to_thread(lambda: self._collection.add(**args))

    async def upsert_many(self, records: Sequence[VectorRecord]) -> None:
        record_list = list(records)
        if record_list:
            args = self._add_args(record_list)
            await asyncio.to_thread(lambda: self._collection.upsert(**args))

    async def search(
        self,
        vector: Sequence[float],
        query_text: str,
        top_k: int = 20,
    ) -> list[SearchResult]:
        res = await asyncio.to_thread(
            self._collection.query,
            query_embeddings=[list(vector)],
            n_results=top_k,
            include=["metadatas", "distances", "documents"],
        )
        return self._assemble(res, top_k)

    async def delete_many(self, chunk_ids: Sequence[str]) -> None:
        ids = list(chunk_ids)
        if ids:
            await asyncio.to_thread(self._collection.delete, ids=ids)

    async def delete_by_document(self, document_id: str) -> None:
        await asyncio.to_thread(self._collection.delete, where={"document_id": document_id})


class ChromaInProcessRepository(VectorStore):
    def __init__(self, config: VectorStoreConfig | None = None):
        provider = ChromaInProcessProvider(config)
        super().__init__(provider, provider.config)
