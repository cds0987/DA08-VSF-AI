"""Reranker — BẢN RIÊNG mcp. Rerank chạy SAU retrieval nên khác rag-worker cũng
không vỡ contract (không đụng không gian vector). v1: noop + lexical.

LLM rerank chưa port sang mcp v1 -> RERANK_PROVIDER=llm sẽ báo lỗi rõ; dùng
`lexical` hoặc `none` (CI/offline dùng `none`/`lexical`).
"""

from __future__ import annotations

from typing import List, Protocol

from app.core.text_utils import overlap_score
from app.core.vectorstore import SearchHit


class Reranker(Protocol):
    def rerank(self, query: str, hits: List[SearchHit], top_k: int, threshold: float) -> List[SearchHit]: ...


class NoopReranker:
    """Giữ nguyên thứ tự vector score, cắt top_k. threshold bỏ qua (score raw)."""

    def rerank(self, query: str, hits: List[SearchHit], top_k: int, threshold: float) -> List[SearchHit]:
        ordered = sorted(hits, key=lambda h: h.score, reverse=True)
        return ordered[:top_k]


class LexicalReranker:
    """Chấm overlap token query↔(caption+parent_text), lọc threshold, cắt top_k."""

    def rerank(self, query: str, hits: List[SearchHit], top_k: int, threshold: float) -> List[SearchHit]:
        scored: list[tuple[float, SearchHit]] = []
        for hit in hits:
            score = overlap_score(query, f"{hit.caption}\n{hit.parent_text}")
            if score >= threshold:
                hit.score = score
                scored.append((score, hit))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [hit for _, hit in scored[:top_k]]


def build_reranker(impl: str) -> Reranker:
    normalized = (impl or "none").strip().lower()
    if normalized == "none":
        return NoopReranker()
    if normalized == "lexical":
        return LexicalReranker()
    if normalized == "llm":
        raise NotImplementedError(
            "LLM rerank chưa port sang mcp v1. Đặt RERANK_PROVIDER=lexical hoặc none."
        )
    raise ValueError(f"RERANK_PROVIDER không hợp lệ: {impl!r} (cho phép: none|lexical|llm)")
