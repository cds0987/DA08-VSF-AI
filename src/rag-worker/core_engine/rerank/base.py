"""Reranker — interface trừu tượng cho bước rerank (search.md §4).

Engine gọi qua interface này => swap LLM-reranker (qua AI gateway) / cross-encoder
/ lexical mà KHÔNG đổi use-case search (hexagonal).
"""

from __future__ import annotations

from typing import List, Protocol, runtime_checkable

from core_engine.types import SearchResult


@runtime_checkable
class Reranker(Protocol):
    async def rerank(
        self,
        query: str,
        results: List[SearchResult],
        top_k: int,
        threshold: float,
    ) -> List[SearchResult]:
        """Gán rerank_score, sort giảm dần, lọc theo threshold, trả tối đa top_k.

        Rerank trên FULL content (parent_text) để bù rủi ro caption-only (search.md §4).
        """
        ...
