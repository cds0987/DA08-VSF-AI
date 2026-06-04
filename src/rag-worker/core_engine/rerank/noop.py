"""NoopRerankerService - keep vector ranking as-is.

Useful for A/B runs that want to disable the rerank stage entirely while still
conforming to the Reranker contract expected by the engine.
"""

from __future__ import annotations

from typing import List

from app.domain.repositories.vector_repository import SearchResult


class NoopRerankerService:
    async def rerank(
        self, query: str, results: List[SearchResult], top_k: int, threshold: float
    ) -> List[SearchResult]:
        del query
        for result in results:
            result.rerank_score = result.score
        return [result for result in results if result.rerank_score >= threshold][:top_k]
