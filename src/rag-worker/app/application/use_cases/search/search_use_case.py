"""SearchUseCase — query-side retrieval CHUYỂN từ mcp-service về rag-worker.

Trước đây mcp-service ĐỌC Qdrant để retrieve; nay rag-worker (bên GHI) cũng phục vụ
SEARCH để gom 1 chỗ logic vector + giữ contract sparse/embed ĐỐI XỨNG với ingest
(cùng provider/dimension/sparse encoding — đảm bảo bằng kiến trúc, không bằng kỷ luật).

Luồng 1 lượt:
  1. embed query qua ProviderEmbeddingService (cùng AI gateway/model/dim như ingest).
  2. vectorstore.search(dense+sparse hybrid hoặc dense trần) với ACL filter.
  3. map SearchHit -> candidate dict (field mapping ĐỐI XỨNG mcp _to_hit) cho caller rerank.

ACL: document_ids là danh sách doc-id mà caller ĐÃ lọc theo quyền. None/rỗng =>
KHÔNG có quyền => kết quả RỖNG (vectorstore._access_filter ép __no_access__). KHÔNG
diễn giải rỗng thành "tìm tất cả".
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import List, Sequence

from core_engine.types import EmbeddingService
from core_engine.vectorstore.store import VectorStore
from core_engine.vectorstore.types import SearchHit

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchCandidate:
    """Một ứng viên trả ra ngoài HTTP (CHƯA rerank). Khớp 1-1 contract /api/search."""

    chunk_id: str
    document_id: str
    document_name: str
    caption: str
    child_text: str
    parent_text: str
    heading_path: List[str]
    score: float
    page_number: int | None
    source_gcs_uri: str
    markdown_gcs_uri: str

    @classmethod
    def from_hit(cls, hit: SearchHit) -> "SearchCandidate":
        return cls(
            chunk_id=hit.chunk_id,
            document_id=hit.document_id,
            document_name=hit.document_name,
            caption=hit.caption,
            child_text=hit.child_text,
            parent_text=hit.parent_text,
            heading_path=list(hit.heading_path),
            score=hit.score,
            page_number=hit.page_number,
            source_gcs_uri=hit.source_gcs_uri,
            markdown_gcs_uri=hit.markdown_gcs_uri,
        )


class SearchUseCase:
    def __init__(
        self,
        embedder: EmbeddingService,
        vectors: VectorStore,
        read_targets: list | None = None,
    ):
        self._embedder = embedder
        self._vectors = vectors
        # SHARD READ: khi corpus được shard N/5 (mỗi doc CHỈ ở 1 collection), 1 collection
        # không đủ recall -> phải query MỌI collection rồi gộp. read_targets = list EmbedTarget
        # (model+embedder+vectors mỗi collection, GỒM primary). None/rỗng -> giữ search
        # 1-collection cũ (replicate/off). Mỗi collection query bằng ĐÚNG model của nó
        # (embed query khớp vector space). Caller rerank như cũ (candidate CHƯA rerank).
        self._read_targets = list(read_targets or [])

    async def search(
        self,
        *,
        query: str,
        document_ids: Sequence[str] | None,
        top_k: int = 20,
    ) -> List[SearchCandidate]:
        top_k = max(1, int(top_k))
        if self._read_targets:
            return await self._search_shard_merge(
                query=query, document_ids=document_ids, top_k=top_k
            )
        # Embed query KHÔNG phụ thuộc ACL: vẫn embed dù document_ids rỗng để giữ chi phí
        # đối xứng + đường code đơn giản; filter rỗng -> vectorstore tự trả [] (ACL).
        query_vector = await self._embedder.embed(query)
        hits = await self._vectors.search(
            query_vector=query_vector,
            query_text=query,
            top_k=top_k,
            document_ids=document_ids,
        )
        return [SearchCandidate.from_hit(hit) for hit in hits]

    async def _search_one_target(
        self,
        target: object,
        *,
        query: str,
        document_ids: Sequence[str] | None,
        top_k: int,
    ) -> List[SearchHit]:
        """Embed query bằng embedder của target -> search collection của target (top_k).

        Giữ ACL filter (document_ids) NHƯ search 1-collection. 1 collection lỗi KHÔNG vỡ
        collection khác (caller gather return_exceptions)."""
        query_vector = await target.embedder.embed(query)
        return await target.vectors.search(
            query_vector=query_vector,
            query_text=query,
            top_k=top_k,
            document_ids=document_ids,
        )

    async def _search_shard_merge(
        self,
        *,
        query: str,
        document_ids: Sequence[str] | None,
        top_k: int,
    ) -> List[SearchCandidate]:
        """Query MỌI collection shard (mỗi cái bằng model riêng) -> GỘP + dedup theo
        chunk_id -> sort theo score -> top_k. Caller rerank sau (đối xứng search 1-collection).

        Mỗi collection lấy top_k để pool ứng viên đủ rộng trước khi rerank. Score giữa các
        vector space KHÁC THANG -> sort chỉ để cắt ngọn ổn định; rerank ở caller mới là xếp
        hạng thật (hợp đồng /api/search: candidate CHƯA rerank)."""
        results = await asyncio.gather(
            *[
                self._search_one_target(
                    t, query=query, document_ids=document_ids, top_k=top_k
                )
                for t in self._read_targets
            ],
            return_exceptions=True,
        )
        merged: dict[str, SearchHit] = {}
        for target, result in zip(self._read_targets, results):
            if isinstance(result, BaseException):
                _logger.warning(
                    "shard_read_target_failed model=%s error=%s",
                    getattr(target, "embed_model", "?"),
                    str(result)[:300],
                )
                continue
            for hit in result:
                # Dedup theo chunk_id: doc chỉ ở 1 collection (shard) nên thường KHÔNG trùng;
                # phòng doc cũ replicate còn nằm nhiều collection -> giữ điểm CAO nhất.
                existing = merged.get(hit.chunk_id)
                if existing is None or hit.score > existing.score:
                    merged[hit.chunk_id] = hit
        ordered = sorted(merged.values(), key=lambda h: h.score, reverse=True)[:top_k]
        return [SearchCandidate.from_hit(hit) for hit in ordered]
