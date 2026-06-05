from __future__ import annotations

import logging

import pytest

from app.core.config import McpSettings
from app.core.search import SearchService
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

    async def search(self, vector, query_text: str, top_k: int) -> list[SearchHit]:
        self.calls.append({"vector": list(vector), "query_text": query_text, "top_k": top_k})
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
@pytest.mark.parametrize(
    "document_ids",
    [
        None,
        [],
        ["doc-1"] * 1000,
    ],
)
async def test_rag_search_accepts_document_ids_edge_cases(
    document_ids, caplog: pytest.LogCaptureFixture
) -> None:
    embedder = StubEmbedder()
    reader = StubReader([SearchHit(chunk_id="c1", score=0.9)])
    reranker = StubReranker()
    service = SearchService(_settings(), embedder, reader, reranker)

    caplog.set_level(logging.INFO)
    hits = await service.rag_search("query text", document_ids=document_ids, top_k=2)

    assert [hit.chunk_id for hit in hits] == ["c1"]
    assert embedder.queries == ["query text"]
    assert reader.calls[0]["top_k"] == 20
    assert reranker.calls[0]["top_k"] == 2
    if document_ids is not None:
        assert "MCP compatibility" in caplog.text
        assert "TODO ACL" not in caplog.text
