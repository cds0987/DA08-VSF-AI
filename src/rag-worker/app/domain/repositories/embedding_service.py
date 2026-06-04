from abc import ABC, abstractmethod
from typing import List


class EmbeddingService(ABC):

    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """Embed 1 đoạn text → vector 1024 dims (BGE-M3)."""

    @abstractmethod
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed nhiều text cùng lúc — dùng khi ingestion chunking."""
