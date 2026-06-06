"""Search orchestration for mcp-service: embed -> retrieve -> rerank."""

from __future__ import annotations

from typing import List, Optional

from app.core.config import McpSettings, load_settings
from app.core.embedding import QueryEmbedder, build_embedder
from app.core.rerank import Reranker, build_reranker
from app.core.vectorstore import QdrantReader, SearchHit

class SearchService:
    def __init__(
        self,
        settings: McpSettings,
        embedder: QueryEmbedder,
        reader: QdrantReader,
        reranker: Reranker,
    ) -> None:
        self._settings = settings
        self._embedder = embedder
        self._reader = reader
        self._reranker = reranker

    async def verify_contract(self, *, expect_data_collection: bool = True):
        return await self._reader.verify_contract(expect_data_collection=expect_data_collection)

    async def aclose(self) -> None:
        embedder_close = getattr(self._embedder, "aclose", None)
        if callable(embedder_close):
            await embedder_close()
        reader_close = getattr(self._reader, "aclose", None)
        if callable(reader_close):
            await reader_close()
        reranker_close = getattr(self._reranker, "aclose", None)
        if callable(reranker_close):
            await reranker_close()

    async def rag_search(
        self,
        query: str,
        document_ids: Optional[List[str]] = None,
        top_k: Optional[int] = None,
    ) -> List[SearchHit]:
        requested_top_k = top_k or self._settings.rerank_top_k
        final_k = max(1, min(requested_top_k, self._settings.top_k_candidates))
        vector = await self._embedder.embed(query)
        candidates = await self._reader.search(
            vector,
            query,
            top_k=self._settings.top_k_candidates,
            document_ids=document_ids,
        )
        return await self._reranker.rerank(
            query, candidates, final_k, self._settings.rerank_threshold
        )


def build_search_service(settings: McpSettings | None = None) -> SearchService:
    settings = settings or load_settings()
    return SearchService(
        settings=settings,
        embedder=build_embedder(settings),
        reader=QdrantReader(settings),
        reranker=build_reranker(settings),
    )
