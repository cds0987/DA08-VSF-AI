"""Search orchestration for mcp-service: rag-worker /api/search -> rerank.

mcp-service = THIN search interface: embed + vector search là việc của rag-worker
(producer/owner của embed model + collection contract). mcp gọi rag-worker qua HTTP
rồi chạy rerank + diversify CỦA NGƯỜI TIÊU THỤ trên ứng viên trả về.
"""

from __future__ import annotations

from typing import Any, List, Optional

import httpx

from app.core.config import McpSettings, load_settings
from app.core.models import SearchHit
from app.core.rerank import Reranker, build_reranker


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


def _candidate_to_hit(item: Any) -> SearchHit:
    """Parse 1 phần tử `candidates` (rag-worker /api/search) -> SearchHit. Trường map 1:1;
    thiếu trường -> default (an toàn cho schema lệch nhẹ)."""
    m = item if isinstance(item, dict) else {}
    return SearchHit(
        chunk_id=str(m.get("chunk_id", "")),
        document_id=str(m.get("document_id", "")),
        document_name=str(m.get("document_name", "")),
        caption=str(m.get("caption", "")),
        child_text=str(m.get("child_text", "")),
        parent_text=str(m.get("parent_text", "")),
        heading_path=list(m.get("heading_path", []) or []),
        score=float(m.get("score")) if m.get("score") is not None else 0.0,
        page_number=m.get("page_number"),
        source_gcs_uri=str(m.get("source_gcs_uri", "")),
        markdown_gcs_uri=str(m.get("markdown_gcs_uri", "")),
    )


class SearchService:
    def __init__(
        self,
        settings: McpSettings,
        reranker: Reranker,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._reranker = reranker
        # httpx client dựng lười + bind vào event-loop đang serve (giống QdrantReader cũ).
        self._client = client

    def _http_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._settings.rag_worker_url.rstrip("/"),
                timeout=self._settings.search_timeout_seconds,
            )
        return self._client

    async def aclose(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            await client.aclose()
        reranker_close = getattr(self._reranker, "aclose", None)
        if callable(reranker_close):
            await reranker_close()

    async def _retrieve(
        self,
        query: str,
        document_ids: Optional[List[str]],
        top_k: int,
    ) -> List[SearchHit]:
        """POST rag-worker /api/search -> candidates -> SearchHit. embed + vector search
        là việc của rag-worker; mcp chỉ tiêu thụ ứng viên."""
        response = await self._http_client().post(
            "/api/search",
            json={"query": query, "document_ids": document_ids, "top_k": top_k},
        )
        response.raise_for_status()
        body = response.json()
        candidates = body.get("candidates") if isinstance(body, dict) else None
        return [_candidate_to_hit(item) for item in (candidates or [])]

    async def rag_search(
        self,
        query: str,
        document_ids: Optional[List[str]] = None,
        top_k: Optional[int] = None,
    ) -> List[SearchHit]:
        requested_top_k = top_k or self._settings.rerank_top_k
        final_k = max(1, min(requested_top_k, self._settings.top_k_candidates))
        candidates = await self._retrieve(
            query, document_ids, top_k=self._settings.top_k_candidates
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
        reranker=build_reranker(settings),
    )
