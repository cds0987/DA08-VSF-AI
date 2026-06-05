from __future__ import annotations

from typing import List, Optional

from app.domain.repositories.vector_repository import SearchResult
from core_engine.engine import HaystackRagEngine


class RetrievalUseCase:
    def __init__(self, engine: HaystackRagEngine):
        self._engine = engine

    async def execute(
        self,
        query_text: str,
        *,
        document_ids: Optional[List[str]] = None,
        top_k: int = 5,
        correlation_id: str | None = None,
    ) -> List[SearchResult]:
        return await self._engine.search(
            query_text,
            top_k=top_k,
            document_ids=document_ids,
            correlation_id=correlation_id,
        )
