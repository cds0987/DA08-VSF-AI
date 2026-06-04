"""LLMReranker — rerank bằng LLM qua AI gateway (LLM-as-reranker, search.md §4).

Chạy CẢ offline lẫn OpenAI: chỉ gọi `provider.chat(capability="rerank")`. Offline
provider trả JSON điểm overlap (mô phỏng contract), OpenAI provider gọi LLM thật —
code path y hệt. Lỗi/parse-fail → fallback lexical (log_event WARNING, không làm vỡ
search). Rerank trên FULL content (parent_text) để bù caption-only (search.md §4).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Dict, List

from app.domain.repositories.vector_repository import SearchResult

from core_engine.ai import AIProvider, RERANK, RERANK_QUERY_MARKER, get_ai_provider
from core_engine.logging_utils import log_event
from core_engine.rerank.lexical import LexicalRerankerService

# Dòng query dùng RERANK_QUERY_MARKER (hằng dùng chung với OfflineProvider._fake_rerank)
# để prompt và parser offline KHÔNG drift. Passages giữ định dạng "[i] text".
RERANK_PROMPT = (
    "Cho một CÂU HỎI và danh sách ĐOẠN đánh số. Chấm mức liên quan mỗi đoạn với "
    'câu hỏi theo thang 0.0–1.0. CHỈ trả JSON dạng {{"0": 0.9, "1": 0.2}} không giải thích.\n\n'
    + RERANK_QUERY_MARKER + " {query}\n\nCÁC ĐOẠN:\n{passages}"
)


class LLMReranker:
    def __init__(self, provider: AIProvider | None = None, *, passage_chars: int = 800):
        self._provider = provider or get_ai_provider()
        # Config-driven params đến từ ${VAR} interpolation dưới dạng string -> coerce.
        self._passage_chars = int(passage_chars)
        self._fallback = LexicalRerankerService()
        self._logger = logging.getLogger(__name__)

    async def rerank(
        self, query: str, results: List[SearchResult], top_k: int, threshold: float
    ) -> List[SearchResult]:
        if not results:
            return []
        passages = "\n".join(
            f"[{index}] {(result.parent_text or result.child_text)[: self._passage_chars]}"
            for index, result in enumerate(results)
        )
        prompt = RERANK_PROMPT.format(query=query, passages=passages)
        try:
            text = await self._provider.chat(prompt, capability=RERANK)
            scores = self._parse_scores(text, len(results))
            for index, result in enumerate(results):
                result.rerank_score = scores.get(index, 0.0)
        except Exception as exc:  # noqa: BLE001
            log_event(
                self._logger,
                logging.WARNING,
                "rerank_fallback",
                stage="rerank",
                error=str(exc),
                candidate_count=len(results),
            )
            return await self._fallback.rerank(query, results, top_k, threshold)
        results.sort(key=lambda result: result.rerank_score, reverse=True)
        return [result for result in results if result.rerank_score >= threshold][:top_k]

    @staticmethod
    def _parse_scores(text: str, n: int) -> Dict[int, float]:
        match = re.search(r"\{.*\}", text or "", re.DOTALL)
        raw = json.loads(match.group(0)) if match else {}
        output: Dict[int, float] = {}
        for key, value in raw.items():
            try:
                index = int(key)
            except (ValueError, TypeError):
                continue
            if 0 <= index < n:
                output[index] = max(0.0, min(1.0, float(value)))
        return output
