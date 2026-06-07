from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List


class EmbeddingService(ABC):
    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """Embed one text into a vector."""

    @abstractmethod
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed many texts while preserving order."""


class VectorRepository(ABC):
    @abstractmethod
    async def upsert_many(self, records) -> None:
        """Store or overwrite many vectors at once."""

    @abstractmethod
    async def upsert(self, chunk_id: str, vector: List[float], payload: dict) -> None:
        """Store one vector + payload."""

    @abstractmethod
    async def list_chunk_ids_by_document(self, document_id: str) -> List[str]:
        """List chunk ids currently stored for a document."""

    @abstractmethod
    async def delete_many(self, chunk_ids: List[str]) -> None:
        """Delete a set of chunk ids."""

    @abstractmethod
    async def delete_by_document(self, document_id: str) -> None:
        """Delete all vectors for a document."""
