from __future__ import annotations

import dataclasses

import pytest

from app.core.config import McpSettings
from app.core.search import SearchService, diversify_by_document
from app.core.vectorstore import SearchHit


class StubEmbedder:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.queries.append(text)
        return [0.1, 0.2]


class StubReader:
    def __init__(self, hits: list[SearchHit]) -> None:
        self.hits = hits
        self.calls: list[dict] = []

    async def search(
        self, vector, query_text: str, top_k: int, document_ids=None
    ) -> list[SearchHit]:
        self.calls.append(
            {
                "vector": list(vector),
                "query_text": query_text,
                "top_k": top_k,
                "document_ids": document_ids,
            }
        )
        return list(self.hits)


class StubReranker:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def rerank(self, query: str, hits: list[SearchHit], top_k: int, threshold: float):
        self.calls.append(
            {"query": query, "hits": [hit.chunk_id for hit in hits], "top_k": top_k, "threshold": threshold}
        )
        return list(hits[:top_k])


def _settings() -> McpSettings:
    return McpSettings(
        host="0.0.0.0",
        port=8003,
        log_level="INFO",
        app_env="development",
        internal_token="",
        provider="qdrant",
        collection="rag_chatbot",
        embed_model="offline",
        dimension=256,
        url="",
        api_key="",
        embed_base_url="",
        embed_api_key="",
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
        options={},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("document_ids", [None, [], ["doc-1"] * 1000])
async def test_rag_search_passes_document_ids_to_reader(document_ids) -> None:
    embedder = StubEmbedder()
    reader = StubReader([SearchHit(chunk_id="c1", score=0.9)])
    reranker = StubReranker()
    service = SearchService(_settings(), embedder, reader, reranker)

    hits = await service.rag_search("query text", document_ids=document_ids, top_k=2)

    assert [hit.chunk_id for hit in hits] == ["c1"]
    assert embedder.queries == ["query text"]
    assert reader.calls[0]["top_k"] == 20
    assert reader.calls[0]["document_ids"] == document_ids
    assert reranker.calls[0]["top_k"] == 2


@pytest.mark.asyncio
async def test_rag_search_uses_configured_rerank_top_k_when_tool_omits_top_k() -> None:
    embedder = StubEmbedder()
    reader = StubReader(
        [
            SearchHit(chunk_id="c1", score=0.9),
            SearchHit(chunk_id="c2", score=0.8),
            SearchHit(chunk_id="c3", score=0.7),
            SearchHit(chunk_id="c4", score=0.6),
        ]
    )
    reranker = StubReranker()
    service = SearchService(_settings(), embedder, reader, reranker)

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
    embedder = StubEmbedder()
    reader = StubReader([_hit("A1", "A", .99), _hit("A2", "A", .98), _hit("A3", "A", .97),
                         _hit("B1", "B", .90), _hit("C1", "C", .80)])
    reranker = StubReranker()
    settings = dataclasses.replace(_settings(), rerank_top_k=2, rerank_max_per_doc=1,
                                   rerank_diversity_pool=3)
    service = SearchService(settings, embedder, reader, reranker)
    hits = await service.rag_search("q", top_k=None)
    # pool = min(#candidates=5, final_k(2)*3=6) = 5 -> rerank rộng hơn final_k(2)
    assert reranker.calls[0]["top_k"] == 5
    # cap 1/doc, k=2 -> A1,B1 (KHÔNG A1,A2)
    assert [h.chunk_id for h in hits] == ["A1", "B1"]
