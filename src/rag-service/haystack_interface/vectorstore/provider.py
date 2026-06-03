from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from app.domain.repositories.vector_repository import SearchResult, UserContext

from haystack_interface.vectorstore.config import VectorStoreConfig
from haystack_interface.vectorstore.types import VectorRecord


class VectorStoreProvider(ABC):
    def __init__(self, config: VectorStoreConfig):
        self.config = config

    @abstractmethod
    async def insert_many(self, records: Sequence[VectorRecord]) -> None:
        """Insert mới hoàn toàn; trùng id phải fail."""

    @abstractmethod
    async def upsert_many(self, records: Sequence[VectorRecord]) -> None:
        """Insert hoặc overwrite theo chunk_id."""

    @abstractmethod
    async def search(
        self,
        vector: Sequence[float],
        query_text: str,
        user_context: UserContext,
        top_k: int = 20,
    ) -> list[SearchResult]:
        """Search thống nhất ra ngoài; bên trong backend có thể hybrid hay dense-only."""

    @abstractmethod
    async def delete_many(self, chunk_ids: Sequence[str]) -> None:
        """Xóa theo chunk_id."""

    @abstractmethod
    async def delete_by_document(self, document_id: str) -> None:
        """Xóa mọi chunk của một document."""
