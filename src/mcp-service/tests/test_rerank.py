from __future__ import annotations

import logging

import pytest

from app.core.rerank import LlmReranker
from app.core.vectorstore import SearchHit


def _hit(chunk_id: str, *, score: float = 0.0, caption: str = "", parent_text: str = "") -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        document_id=f"{chunk_id}-doc",
        document_name=f"{chunk_id}.pdf",
        caption=caption or chunk_id,
        parent_text=parent_text or f"body for {chunk_id}",
        score=score,
    )


@pytest.mark.asyncio
async def test_llm_reranker_orders_filters_and_clamps_scores() -> None:
    async def score_batch(query: str, passages: list[str]) -> dict[int, float]:
        assert query == "leave policy"
        assert len(passages) == 3
        return {0: 0.2, 1: 1.4, 2: 0.75}

    reranker = LlmReranker(
        model="gpt-4o-mini",
        api_key="",
        base_url="",
        timeout_seconds=10.0,
        batch_size=8,
        passage_chars=100,
        score_batch=score_batch,
    )

    hits = [_hit("a"), _hit("b"), _hit("c")]
    reranked = await reranker.rerank("leave policy", hits, top_k=2, threshold=0.5)

    assert [hit.chunk_id for hit in reranked] == ["b", "c"]
    assert reranked[0].score == 1.0
    assert reranked[1].score == 0.75


@pytest.mark.asyncio
async def test_llm_reranker_falls_back_to_noop_when_provider_fails(caplog: pytest.LogCaptureFixture) -> None:
    async def score_batch(query: str, passages: list[str]) -> dict[int, float]:
        raise TimeoutError("gateway timeout")

    reranker = LlmReranker(
        model="gpt-4o-mini",
        api_key="",
        base_url="",
        timeout_seconds=10.0,
        batch_size=2,
        passage_chars=100,
        score_batch=score_batch,
    )
    hits = [_hit("slow", score=0.4), _hit("fast", score=0.9)]

    caplog.set_level(logging.WARNING)
    reranked = await reranker.rerank("leave policy", hits, top_k=2, threshold=0.8)

    assert [hit.chunk_id for hit in reranked] == ["fast", "slow"]
    assert "rerank_fallback" in caplog.text
