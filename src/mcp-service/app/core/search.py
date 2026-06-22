"""Search orchestration for mcp-service: embed -> retrieve -> rerank."""

from __future__ import annotations

from typing import List, Optional

from app.core.config import McpSettings, load_settings
from app.core.embedding import QueryEmbedder, build_embedder
from app.core.rerank import Reranker, build_reranker
from app.core.vectorstore import QdrantReader, SearchHit


def diversify_by_document(hits: List[SearchHit], k: int, max_per_doc: int) -> List[SearchHit]:
    """Chọn top-k giữ ĐA DẠNG document: tối đa `max_per_doc` chunk mỗi document, theo thứ tự
    rerank (score giảm dần). Chống "1 doc thống trị top-k" -> doc nhỏ/đúng bị chôn + precision
    cross-doc kém. Nếu cap để lại chỗ trống -> fill phần dư (chunk vượt-cap) theo thứ tự score
    để KHÔNG trả ít hơn k khi còn ứng viên. max_per_doc<=0 -> bỏ qua (cắt thẳng top-k)."""
    if max_per_doc <= 0 or k <= 0:
        return hits[:k]
    chosen: list[SearchHit] = []
    leftover: list[SearchHit] = []
    per: dict[str, int] = {}
    for h in hits:
        d = h.document_id or ""
        if per.get(d, 0) < max_per_doc:
            chosen.append(h)
            per[d] = per.get(d, 0) + 1
            if len(chosen) >= k:
                return chosen
        else:
            leftover.append(h)
    for h in leftover:                  # cap thiếu k -> bù bằng chunk vượt-cap (đã sort score)
        if len(chosen) >= k:
            break
        chosen.append(h)
    return chosen[:k]


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
        max_per_doc = self._settings.rerank_max_per_doc
        if max_per_doc <= 0:                                   # TẮT -> hành vi cũ
            return await self._reranker.rerank(
                query, candidates, final_k, self._settings.rerank_threshold
            )
        # Rerank POOL rộng hơn (final_k * pool) rồi chọn final_k đa dạng document -> doc khác
        # (gồm doc đúng/nhỏ) có cơ hội nổi lên thay vì bị 1 doc chiếm hết top-k.
        pool = min(len(candidates), max(final_k, final_k * self._settings.rerank_diversity_pool))
        reranked = await self._reranker.rerank(
            query, candidates, pool, self._settings.rerank_threshold
        )
        return diversify_by_document(reranked, final_k, max_per_doc)


def build_search_service(settings: McpSettings | None = None) -> SearchService:
    settings = settings or load_settings()
    return SearchService(
        settings=settings,
        embedder=build_embedder(settings),
        reader=QdrantReader(settings),
        reranker=build_reranker(settings),
    )
