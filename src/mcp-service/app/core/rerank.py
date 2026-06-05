"""Reranker for mcp-service: none, lexical, and llm with safe fallback."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Awaitable, Callable, List, Protocol

from app.core.text_utils import overlap_score
from app.core.vectorstore import SearchHit

if TYPE_CHECKING:
    from app.core.config import McpSettings

logger = logging.getLogger(__name__)

ScoreBatchFn = Callable[[str, list[str]], Awaitable[dict[int, float]]]

_RERANK_SYSTEM_PROMPT = (
    "Score each passage for relevance to the query on a 0.0 to 1.0 scale. "
    'Return JSON only, for example {"0": 0.91, "1": 0.24}.'
)


class Reranker(Protocol):
    async def rerank(
        self, query: str, hits: List[SearchHit], top_k: int, threshold: float
    ) -> List[SearchHit]: ...


class NoopReranker:
    async def rerank(
        self, query: str, hits: List[SearchHit], top_k: int, threshold: float
    ) -> List[SearchHit]:
        ordered = sorted(hits, key=lambda h: h.score, reverse=True)
        return ordered[:top_k]


class LexicalReranker:
    async def rerank(
        self, query: str, hits: List[SearchHit], top_k: int, threshold: float
    ) -> List[SearchHit]:
        scored: list[tuple[float, SearchHit]] = []
        for hit in hits:
            score = overlap_score(query, f"{hit.caption}\n{hit.parent_text}")
            if score >= threshold:
                hit.score = score
                scored.append((score, hit))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [hit for _, hit in scored[:top_k]]


class LlmReranker:
    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
        batch_size: int,
        passage_chars: int,
        score_batch: ScoreBatchFn | None = None,
        fallback: Reranker | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url or None
        self._timeout_seconds = timeout_seconds
        self._batch_size = max(1, int(batch_size))
        self._passage_chars = max(1, int(passage_chars))
        self._score_batch = score_batch or self._score_batch_with_openai
        self._fallback = fallback or NoopReranker()

    async def rerank(
        self, query: str, hits: List[SearchHit], top_k: int, threshold: float
    ) -> List[SearchHit]:
        if not hits:
            return []

        scored: list[tuple[float, SearchHit]] = []
        try:
            for start in range(0, len(hits), self._batch_size):
                batch_hits = hits[start : start + self._batch_size]
                passages = [self._passage_text(hit) for hit in batch_hits]
                batch_scores = await self._score_batch(query, passages)
                for index, hit in enumerate(batch_hits):
                    score = self._normalize_score(batch_scores.get(index, 0.0))
                    hit.score = score
                    if score >= threshold:
                        scored.append((score, hit))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "rerank_fallback provider=llm candidate_count=%d error=%s",
                len(hits),
                exc,
            )
            return await self._fallback.rerank(query, hits, top_k, threshold)

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [hit for _, hit in scored[:top_k]]

    async def _score_batch_with_openai(self, query: str, passages: list[str]) -> dict[int, float]:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=self._api_key or None,
            base_url=self._base_url,
            timeout=self._timeout_seconds,
        )
        try:
            response = await client.chat.completions.create(
                model=self._model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _RERANK_SYSTEM_PROMPT},
                    {"role": "user", "content": self._build_user_prompt(query, passages)},
                ],
            )
        finally:
            await client.close()

        message = response.choices[0].message.content or ""
        return self._parse_scores(message, len(passages))

    def _build_user_prompt(self, query: str, passages: list[str]) -> str:
        numbered_passages = "\n".join(
            f"[{index}] {passage}" for index, passage in enumerate(passages)
        )
        return f"QUERY: {query}\n\nPASSAGES:\n{numbered_passages}"

    def _passage_text(self, hit: SearchHit) -> str:
        return f"{hit.caption}\n{hit.parent_text[: self._passage_chars]}".strip()

    @staticmethod
    def _normalize_score(value: float) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, numeric))

    @classmethod
    def _parse_scores(cls, text: str, count: int) -> dict[int, float]:
        match = re.search(r"\{.*\}", text or "", re.DOTALL)
        raw = json.loads(match.group(0)) if match else {}
        scores: dict[int, float] = {}
        if not isinstance(raw, dict):
            return scores
        for key, value in raw.items():
            try:
                index = int(key)
            except (TypeError, ValueError):
                continue
            if 0 <= index < count:
                scores[index] = cls._normalize_score(value)
        return scores


def build_reranker(settings: McpSettings | str) -> Reranker:
    normalized = settings if isinstance(settings, str) else settings.rerank_impl
    normalized = (normalized or "none").strip().lower()
    if normalized == "none":
        return NoopReranker()
    if normalized == "lexical":
        return LexicalReranker()
    if normalized == "llm":
        if isinstance(settings, str):
            raise ValueError("build_reranker('llm') needs settings for model and gateway config.")
        return LlmReranker(
            model=settings.rerank_model,
            api_key=settings.rerank_api_key or settings.embed_api_key,
            base_url=settings.rerank_base_url or settings.embed_base_url,
            timeout_seconds=settings.rerank_timeout_seconds,
            batch_size=settings.rerank_batch_size,
            passage_chars=settings.rerank_passage_chars,
        )
    raise ValueError(
        f"RERANK_PROVIDER khong hop le: {normalized!r} (cho phep: none|lexical|llm)"
    )
