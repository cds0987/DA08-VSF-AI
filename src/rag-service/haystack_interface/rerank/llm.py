"""LLMReranker — rerank bằng LLM qua AI gateway (LLM-as-reranker, search.md §4).

Chạy CẢ offline lẫn OpenAI: chỉ gọi `provider.chat(capability="rerank")`. Offline
provider trả JSON điểm overlap (mô phỏng contract), OpenAI provider gọi LLM thật —
code path y hệt. Lỗi/parse-fail → fallback lexical (không làm vỡ search).

Rerank trên FULL content (parent_text) để bù caption-only (search.md §4).
"""

from __future__ import annotations

import json
import re
from typing import Dict, List

from app.domain.repositories.vector_repository import SearchResult

from haystack_interface.ai import AIProvider, RERANK, get_ai_provider
from haystack_interface.rerank.lexical import LexicalRerankerService

# Contract prompt — offline_provider._fake_rerank đọc đúng định dạng này
# (dòng `CÂU HỎI:` + các dòng `[i] passage`).
RERANK_PROMPT = (
    "Cho một CÂU HỎI và danh sách ĐOẠN đánh số. Chấm mức liên quan mỗi đoạn với "
    'câu hỏi theo thang 0.0–1.0. CHỈ trả JSON dạng {{"0": 0.9, "1": 0.2}} không giải thích.\n\n'
    "CÂU HỎI: {query}\n\nCÁC ĐOẠN:\n{passages}"
)


class LLMReranker:
    def __init__(self, provider: AIProvider | None = None, *, passage_chars: int = 800):
        self._provider = provider or get_ai_provider()
        self._passage_chars = passage_chars
        self._fallback = LexicalRerankerService()

    async def rerank(
        self, query: str, results: List[SearchResult], top_k: int, threshold: float
    ) -> List[SearchResult]:
        if not results:
            return []
        passages = "\n".join(
            f"[{i}] {(r.parent_text or r.child_text)[: self._passage_chars]}"
            for i, r in enumerate(results)
        )
        prompt = RERANK_PROMPT.format(query=query, passages=passages)
        try:
            text = await self._provider.chat(prompt, capability=RERANK)
            scores = self._parse_scores(text, len(results))
            for i, r in enumerate(results):
                r.rerank_score = scores.get(i, 0.0)
        except Exception as e:  # noqa: BLE001 — gateway lỗi không làm vỡ search
            print("  rerank fail -> lexical fallback:", e)
            return await self._fallback.rerank(query, results, top_k, threshold)
        results.sort(key=lambda r: r.rerank_score, reverse=True)
        return [r for r in results if r.rerank_score >= threshold][:top_k]

    @staticmethod
    def _parse_scores(text: str, n: int) -> Dict[int, float]:
        m = re.search(r"\{.*\}", text or "", re.DOTALL)
        raw = json.loads(m.group(0)) if m else {}
        out: Dict[int, float] = {}
        for k, v in raw.items():
            try:
                idx = int(k)
            except (ValueError, TypeError):
                continue
            if 0 <= idx < n:
                out[idx] = max(0.0, min(1.0, float(v)))
        return out
