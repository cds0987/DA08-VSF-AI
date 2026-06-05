"""Search orchestration for mcp-service: embed -> retrieve -> rerank."""

from __future__ import annotations

import logging
from typing import List, Optional

from app.core.config import McpSettings, load_settings
from app.core.embedding import QueryEmbedder, build_embedder
from app.core.rerank import Reranker, build_reranker
from app.core.vectorstore import QdrantReader, SearchHit

logger = logging.getLogger(__name__)


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

    async def rag_search(
        self,
        query: str,
        document_ids: Optional[List[str]] = None,
        top_k: Optional[int] = None,
    ) -> List[SearchHit]:
        if document_ids is not None:
            logger.info(
                "rag_search received %d document_ids for MCP compatibility; "
                "document ACL filtering is owned by another service.",
                len(document_ids),
            )

        final_k = top_k or self._settings.rerank_top_k
        vector = await self._embedder.embed(query)
        candidates = await self._reader.search(
            vector, query, top_k=self._settings.top_k_candidates
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
