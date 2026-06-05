from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List


@dataclass
class SearchLineage:
    source_uri: str = ""
    artifact_uri: str = ""


@dataclass
class SearchResult:
    correlation_id: str = ""
    unit_id: str = ""
    parent_id: str = ""
    document_id: str = ""
    display_name: str = ""
    file_type: str = ""
    page_number: int = 0
    caption: str = ""
    content: str = ""
    heading_path: List[str] = field(default_factory=list)
    lineage: SearchLineage = field(default_factory=SearchLineage)
    score: float = 0.0
    rerank_score: float = 0.0

    @property
    def chunk_id(self) -> str:
        return self.unit_id

    @property
    def document_name(self) -> str:
        return self.display_name

    @property
    def section_title(self) -> str:
        return self.heading_path[-1] if self.heading_path else ""

    @property
    def child_text(self) -> str:
        return self.caption

    @property
    def parent_text(self) -> str:
        return self.content


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
    async def hybrid_search(
        self,
        vector: List[float],
        query_text: str,
        top_k: int = 20,
    ) -> List[SearchResult]:
        """Dense/hybrid retrieval returning raw search results."""

    @abstractmethod
    async def list_chunk_ids_by_document(self, document_id: str) -> List[str]:
        """List chunk ids currently stored for a document."""

    @abstractmethod
    async def delete_many(self, chunk_ids: List[str]) -> None:
        """Delete a set of chunk ids."""

    @abstractmethod
    async def delete_by_document(self, document_id: str) -> None:
        """Delete all vectors for a document."""
