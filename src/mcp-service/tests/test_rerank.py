from __future__ import annotations

import logging

import pytest

from app.core.rerank import CohereRerankReranker, LlmReranker
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


@pytest.mark.asyncio
async def test_cohere_reranker_maps_index_sorts_and_filters() -> None:
    # API trả results đã sort desc theo relevance_score, index trỏ về doc gốc.
    async def post_fn(query: str, documents: list[str], top_n: int) -> dict:
        assert query == "thủ đô việt nam"
        assert top_n == 2  # min(top_k, len(docs))
        return {"results": [
            {"index": 1, "relevance_score": 0.94},
            {"index": 0, "relevance_score": 0.48},
            {"index": 2, "relevance_score": 0.10},
        ]}

    reranker = CohereRerankReranker(
        model="cohere/rerank-4-pro", api_key="k", base_url="https://x/api/v1",
        timeout_seconds=10.0, post_fn=post_fn,
    )
    hits = [_hit("hcm"), _hit("hanoi"), _hit("danang")]
    reranked = await reranker.rerank("thủ đô việt nam", hits, top_k=2, threshold=0.35)

    assert [h.chunk_id for h in reranked] == ["hanoi", "hcm"]  # sort theo score API
    assert reranked[0].score == 0.94 and reranked[1].score == 0.48  # danang (0.10) bị threshold loại


@pytest.mark.asyncio
async def test_cohere_reranker_threshold_filters_all_keeps_top1() -> None:
    async def post_fn(query: str, documents: list[str], top_n: int) -> dict:
        return {"results": [{"index": 0, "relevance_score": 0.2}, {"index": 1, "relevance_score": 0.1}]}

    reranker = CohereRerankReranker(
        model="m", api_key="", base_url="https://x", timeout_seconds=10.0, post_fn=post_fn,
    )
    hits = [_hit("a"), _hit("b")]
    reranked = await reranker.rerank("q", hits, top_k=2, threshold=0.9)  # lọc sạch
    assert [h.chunk_id for h in reranked] == ["a"]  # giữ top-1 theo điểm API, không rỗng


@pytest.mark.asyncio
async def test_cohere_reranker_falls_back_to_vector_order_on_error(caplog: pytest.LogCaptureFixture) -> None:
    async def post_fn(query: str, documents: list[str], top_n: int) -> dict:
        raise TimeoutError("openrouter 503")

    reranker = CohereRerankReranker(
        model="m", api_key="", base_url="https://x", timeout_seconds=10.0, post_fn=post_fn,
    )
    hits = [_hit("slow", score=0.4), _hit("fast", score=0.9)]
    caplog.set_level(logging.WARNING)
    reranked = await reranker.rerank("q", hits, top_k=2, threshold=0.5)
    assert [h.chunk_id for h in reranked] == ["fast", "slow"]  # vector-order
    assert "rerank_fallback provider=cohere" in caplog.text


def test_parse_scores_ignores_noise_and_clamps_values() -> None:
    parsed = LlmReranker._parse_scores(
        'prefix {"0": 1.2, "1": -0.3, "x": 0.9, "2": "0.7", "8": 0.5} suffix',
        count=3,
    )

    assert parsed == {0: 1.0, 1: 0.0, 2: 0.7}
