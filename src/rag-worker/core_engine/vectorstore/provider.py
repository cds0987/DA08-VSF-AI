from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from core_engine.vectorstore.config import VectorStoreConfig
from core_engine.vectorstore.types import VectorRecord


class VectorStoreProvider(ABC):
    def __init__(self, config: VectorStoreConfig):
        self.config = config

    @abstractmethod
    async def insert_many(self, records: Sequence[VectorRecord]) -> None:
        """Insert moi hoan toan; trung id phai fail."""

    @abstractmethod
    async def upsert_many(self, records: Sequence[VectorRecord]) -> None:
        """Insert hoac overwrite theo chunk_id."""

    @abstractmethod
    async def list_chunk_ids_by_document(self, document_id: str) -> list[str]:
        """Tra ve toan bo chunk ids hien co cua mot document."""

    @abstractmethod
    async def delete_many(self, chunk_ids: Sequence[str]) -> None:
        """Xoa theo chunk_id."""

    @abstractmethod
    async def delete_by_document(self, document_id: str) -> None:
        """Xoa moi chunk cua mot document."""
