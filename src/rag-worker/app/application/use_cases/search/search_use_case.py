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

from dataclasses import dataclass
from typing import List, Sequence

from core_engine.types import EmbeddingService
from core_engine.vectorstore.store import VectorStore
from core_engine.vectorstore.types import SearchHit


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
    def __init__(self, embedder: EmbeddingService, vectors: VectorStore):
        self._embedder = embedder
        self._vectors = vectors

    async def search(
        self,
        *,
        query: str,
        document_ids: Sequence[str] | None,
        top_k: int = 20,
    ) -> List[SearchCandidate]:
        top_k = max(1, int(top_k))
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
