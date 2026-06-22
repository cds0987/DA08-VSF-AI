"""Reranker for mcp-service: none, lexical, and llm with safe fallback.

NOTE(ops): prod tạm dùng 'lexical' (xem deploy/env/mcp-service.env). Provider 'llm' với
RERANK_THRESHOLD=0.7 từng lọc sạch hit -> RAG 0 sources -> deploy smoke fail. Lexical
(overlap ratio) cần threshold thấp. Calibrate lại trước khi bật 'llm'.
"""

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
            lex = overlap_score(query, f"{hit.caption}\n{hit.parent_text}")
            if lex >= threshold:
                scored.append((lex, hit))  # sort by lex, keep original vector score
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
        self._client = None

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
            ordered = sorted(hits, key=lambda h: h.score, reverse=True)[:top_k]
            for hit in ordered:
                hit.score = 0.5
            return ordered

        scored.sort(key=lambda pair: pair[0], reverse=True)
        result = [hit for _, hit in scored[:top_k]]
        if not result:
            logger.warning("rerank_threshold_filtered_all candidates=%d threshold=%s", len(hits), threshold)
            return sorted(hits, key=lambda h: h.score, reverse=True)[:1]
        return result

    async def _score_batch_with_openai(self, query: str, passages: list[str]) -> dict[int, float]:
        response = await self._openai_client().chat.completions.create(
            model=self._model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _RERANK_SYSTEM_PROMPT},
                {"role": "user", "content": self._build_user_prompt(query, passages)},
            ],
        )

        message = response.choices[0].message.content or ""
        return self._parse_scores(message, len(passages))

    def _openai_client(self):
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=self._api_key or None,
                base_url=self._base_url,
                timeout=self._timeout_seconds,
            )
        return self._client

    async def aclose(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            await client.close()

    def _build_user_prompt(self, query: str, passages: list[str]) -> str:
        numbered_passages = "\n".join(
            f"[{index}] {passage}" for index, passage in enumerate(passages)
        )
        return f"QUERY: {query}\n\nPASSAGES:\n{numbered_passages}"

    def _passage_text(self, hit: SearchHit) -> str:
        body = (hit.child_text or hit.parent_text)[: self._passage_chars]
        return f"{hit.caption}\n{body}".strip()

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


def _clamp01(value: object) -> float:
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))


class CohereRerankReranker:
    """Rerank qua endpoint /rerank kiểu Cohere (OpenRouter proxy 'cohere/rerank-4-pro',
    hoặc Cohere/Jina/Voyage trực tiếp). KHÁC LlmReranker (chat.completions): đây là rerank
    endpoint CHUYÊN DỤNG -> 1 HTTP call cho cả batch, trả relevance_score 0..1 ĐÃ SORT giảm
    dần. base_url + '/rerank' (vd https://openrouter.ai/api/v1/rerank).

    Lỗi mạng/HTTP/parse -> fallback vector-order (non-fatal): citation luôn ra như LlmReranker,
    KHÔNG để rerank hỏng làm RAG 0 nguồn.
    """

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
        passage_chars: int = 800,
        post_fn: Callable[[str, list[str], int], Awaitable[dict]] | None = None,
        fallback: Reranker | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = (base_url or "").rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._passage_chars = max(1, int(passage_chars))
        self._post_fn = post_fn or self._post_with_httpx
        self._fallback = fallback or NoopReranker()

    async def rerank(
        self, query: str, hits: List[SearchHit], top_k: int, threshold: float
    ) -> List[SearchHit]:
        if not hits:
            return []
        documents = [self._passage_text(hit) for hit in hits]
        top_n = max(1, min(top_k, len(documents)))
        try:
            data = await self._post_fn(query, documents, top_n)
            results = data.get("results") or []
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "rerank_fallback provider=cohere candidate_count=%d error=%s", len(hits), exc
            )
            ordered = sorted(hits, key=lambda h: h.score, reverse=True)[:top_k]
            for hit in ordered:
                hit.score = 0.5
            return ordered

        scored: list[SearchHit] = []
        for item in results:
            idx = item.get("index")
            if not isinstance(idx, int) or not (0 <= idx < len(hits)):
                continue
            score = _clamp01(item.get("relevance_score", 0.0))
            hit = hits[idx]
            hit.score = score
            if score >= threshold:
                scored.append(hit)  # API đã sort desc -> giữ nguyên thứ tự
        result = scored[:top_k]
        if not result:
            # threshold lọc sạch -> giữ top-1 theo điểm API để không trả rỗng (như LlmReranker).
            logger.warning(
                "rerank_threshold_filtered_all provider=cohere candidates=%d threshold=%s",
                len(hits), threshold,
            )
            best = max(
                (r for r in results if isinstance(r.get("index"), int)
                 and 0 <= r["index"] < len(hits)),
                key=lambda r: _clamp01(r.get("relevance_score", 0.0)),
                default=None,
            )
            if best is not None:
                hit = hits[best["index"]]
                hit.score = _clamp01(best.get("relevance_score", 0.0))
                return [hit]
            return sorted(hits, key=lambda h: h.score, reverse=True)[:1]
        return result

    async def _post_with_httpx(self, query: str, documents: list[str], top_n: int) -> dict:
        import httpx

        payload = {
            "model": self._model,
            "query": query,
            "documents": documents,
            "top_n": top_n,
            "return_documents": False,  # không cần echo text -> payload nhẹ
        }
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            resp = await client.post(
                f"{self._base_url}/rerank", json=payload, headers=headers
            )
            resp.raise_for_status()
            return resp.json()

    def _passage_text(self, hit: SearchHit) -> str:
        body = (hit.child_text or hit.parent_text or "")[: self._passage_chars]
        return f"{hit.caption}\n{body}".strip() if hit.caption else body

    async def aclose(self) -> None:
        return


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
    if normalized == "cohere":
        if isinstance(settings, str):
            raise ValueError("build_reranker('cohere') needs settings for model and endpoint.")
        return CohereRerankReranker(
            model=settings.rerank_model,
            api_key=settings.rerank_api_key,
            # KHÔNG fallback embed_base_url: ai-router không có /rerank. Bắt buộc RERANK_BASE_URL.
            base_url=settings.rerank_base_url,
            timeout_seconds=settings.rerank_timeout_seconds,
            passage_chars=settings.rerank_passage_chars,
        )
    raise ValueError(
        f"RERANK_PROVIDER khong hop le: {normalized!r} (cho phep: none|lexical|llm|cohere)"
    )
