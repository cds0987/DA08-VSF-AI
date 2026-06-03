from __future__ import annotations

from typing import List

from app.domain.repositories.vector_repository import SearchResult
from haystack_interface.engine import HaystackRagEngine


class RetrievalUseCase:
    def __init__(self, engine: HaystackRagEngine):
        self._engine = engine

    async def execute(
        self,
        question: str,
        *,
        correlation_id: str | None = None,
    ) -> List[SearchResult]:
        return await self._engine.search(question, correlation_id=correlation_id)
