from __future__ import annotations

import dataclasses

import pytest

from app.core.config import McpSettings
from app.core.models import SearchHit
from app.core.search import SearchService, diversify_by_document


class FakeResponse:
    def __init__(self, candidates: list[dict]) -> None:
        self._candidates = candidates

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"candidates": self._candidates}


class FakeHttpClient:
    """Giả httpx.AsyncClient: ghi lại POST /api/search rồi trả candidates cấu hình sẵn."""

    def __init__(self, candidates: list[dict]) -> None:
        self._candidates = candidates
        self.calls: list[dict] = []

    async def post(self, url: str, json=None):
        self.calls.append({"url": url, "json": json})
        return FakeResponse(self._candidates)

    async def aclose(self) -> None:
        return None


class StubReranker:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def rerank(self, query: str, hits: list[SearchHit], top_k: int, threshold: float):
        self.calls.append(
            {"query": query, "hits": [hit.chunk_id for hit in hits], "top_k": top_k, "threshold": threshold}
        )
        return list(hits[:top_k])


def _candidate(chunk_id: str, *, document_id: str = "", score: float = 0.9) -> dict:
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "document_name": f"{chunk_id}.pdf",
        "caption": "cap",
        "child_text": "child",
        "parent_text": "parent",
        "heading_path": ["H1"],
        "score": score,
        "page_number": 1,
        "source_gcs_uri": "gs://bucket/doc.pdf",
        "markdown_gcs_uri": "gs://bucket/doc.md",
    }


def _settings() -> McpSettings:
    return McpSettings(
        host="0.0.0.0",
        port=8003,
        log_level="INFO",
        app_env="development",
        internal_token="",
        rag_worker_url="http://rag-worker:8000",
        search_timeout_seconds=30.0,
        rerank_impl="none",
        rerank_model="gpt-4o-mini",
        rerank_base_url="",
        rerank_api_key="",
        rerank_timeout_seconds=30.0,
        rerank_batch_size=8,
        rerank_passage_chars=800,
        top_k_candidates=20,
        rerank_top_k=3,
        rerank_threshold=0.6,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("document_ids", [None, [], ["doc-1"] * 1000])
async def test_rag_search_posts_to_rag_worker_and_returns_results(document_ids) -> None:
    client = FakeHttpClient([_candidate("c1")])
    reranker = StubReranker()
    service = SearchService(_settings(), reranker, client=client)

    hits = await service.rag_search("query text", document_ids=document_ids, top_k=2)

    assert [hit.chunk_id for hit in hits] == ["c1"]
    # POST tới /api/search với top_k_candidates (20), document_ids passthrough.
    assert client.calls[0]["url"] == "/api/search"
    assert client.calls[0]["json"] == {
        "query": "query text",
        "document_ids": document_ids,
        "top_k": 20,
    }
    assert reranker.calls[0]["top_k"] == 2


@pytest.mark.asyncio
async def test_candidate_fields_map_one_to_one_to_search_hit() -> None:
    client = FakeHttpClient([_candidate("c1", document_id="doc-1", score=0.42)])
    service = SearchService(_settings(), StubReranker(), client=client)

    hits = await service.rag_search("q", document_ids=["doc-1"], top_k=1)

    hit = hits[0]
    assert hit.chunk_id == "c1"
    assert hit.document_id == "doc-1"
    assert hit.document_name == "c1.pdf"
    assert hit.caption == "cap"
    assert hit.child_text == "child"
    assert hit.parent_text == "parent"
    assert hit.heading_path == ["H1"]
    assert hit.score == 0.42
    assert hit.page_number == 1
    assert hit.source_gcs_uri == "gs://bucket/doc.pdf"
    assert hit.markdown_gcs_uri == "gs://bucket/doc.md"


@pytest.mark.asyncio
async def test_rag_search_uses_configured_rerank_top_k_when_tool_omits_top_k() -> None:
    client = FakeHttpClient(
        [_candidate("c1"), _candidate("c2"), _candidate("c3"), _candidate("c4")]
    )
    reranker = StubReranker()
    service = SearchService(_settings(), reranker, client=client)

    hits = await service.rag_search("query text", document_ids=["doc-1"], top_k=None)

    assert [hit.chunk_id for hit in hits] == ["c1", "c2", "c3"]
    assert reranker.calls[0]["top_k"] == 3


def _hit(cid, doc, score):
    return SearchHit(chunk_id=cid, document_id=doc, score=score)


def test_diversify_caps_per_doc_and_fills_to_k() -> None:
    # doc A thống trị (A1..A4) + B,C -> cap 2/doc, k=4 -> A,A,B,C (đa dạng), KHÔNG toàn A.
    hits = [_hit("A1", "A", 0.99), _hit("A2", "A", 0.98), _hit("A3", "A", 0.97),
            _hit("A4", "A", 0.96), _hit("B1", "B", 0.90), _hit("C1", "C", 0.80)]
    out = diversify_by_document(hits, k=4, max_per_doc=2)
    assert [h.chunk_id for h in out] == ["A1", "A2", "B1", "C1"]   # A capped tại 2
    assert {h.document_id for h in out} == {"A", "B", "C"}


def test_diversify_fills_with_overcap_when_not_enough_docs() -> None:
    # chỉ 2 doc nhưng k=4, cap=2 -> chọn A,A,B,B (đủ k, không trả ít hơn).
    hits = [_hit("A1", "A", .9), _hit("A2", "A", .8), _hit("A3", "A", .7), _hit("B1", "B", .6)]
    out = diversify_by_document(hits, k=4, max_per_doc=2)
    assert [h.chunk_id for h in out] == ["A1", "A2", "B1", "A3"]   # bù A3 (vượt-cap) để đủ 4


def test_diversify_disabled_passthrough() -> None:
    hits = [_hit("A1", "A", .9), _hit("A2", "A", .8)]
    assert diversify_by_document(hits, k=2, max_per_doc=0) == hits[:2]


@pytest.mark.asyncio
async def test_rag_search_applies_diversity_with_wider_pool() -> None:
    client = FakeHttpClient([
        _candidate("A1", document_id="A", score=.99),
        _candidate("A2", document_id="A", score=.98),
        _candidate("A3", document_id="A", score=.97),
        _candidate("B1", document_id="B", score=.90),
        _candidate("C1", document_id="C", score=.80),
    ])
    reranker = StubReranker()
    settings = dataclasses.replace(_settings(), rerank_top_k=2, rerank_max_per_doc=1,
                                   rerank_diversity_pool=3)
    service = SearchService(settings, reranker, client=client)
    hits = await service.rag_search("q", top_k=None)
    # pool = min(#candidates=5, final_k(2)*3=6) = 5 -> rerank rộng hơn final_k(2)
    assert reranker.calls[0]["top_k"] == 5
    # cap 1/doc, k=2 -> A1,B1 (KHÔNG A1,A2)
    assert [h.chunk_id for h in hits] == ["A1", "B1"]
