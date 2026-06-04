"""LexicalRerankerService — rerank offline thuần (KHÔNG AI).

Chấm bằng độ phủ token query↔full content (parent_text). Là stub cho cross-encoder
thật VÀ là fallback an toàn cho LLMReranker khi gateway lỗi (không làm vỡ search).
"""

from __future__ import annotations

from typing import List

from app.domain.repositories.vector_repository import SearchResult

from core_engine.text_utils import overlap_score


class LexicalRerankerService:
    async def rerank(
        self, query: str, results: List[SearchResult], top_k: int, threshold: float
    ) -> List[SearchResult]:
        for r in results:
            r.rerank_score = overlap_score(query, r.parent_text or r.child_text)
        results.sort(key=lambda r: r.rerank_score, reverse=True)
        return [r for r in results if r.rerank_score >= threshold][:top_k]
