"""InMemoryVectorRepository — port VectorRepository trên Haystack InMemory store.

Hybrid retrieval (vector + BM25, hợp nhất bằng RRF) qua Haystack Pipeline. KHÔNG
rerank ở đây — rerank là bước riêng (search.md §4). Production: đổi sang Qdrant
store + hybrid native, KHÔNG đổi chữ ký port (hexagonal — execution-fallback.md §4b).

Đây là phần "core working" Haystack: Pipeline BM25 + EmbeddingRetriever + RRF joiner.
"""

from __future__ import annotations

import asyncio
from typing import List

from haystack import Document, Pipeline
from haystack.document_stores.in_memory import InMemoryDocumentStore
from haystack.document_stores.types import DuplicatePolicy
from haystack.components.retrievers.in_memory import (
    InMemoryBM25Retriever,
    InMemoryEmbeddingRetriever,
)
from haystack.components.joiners.document_joiner import DocumentJoiner

from app.domain.repositories.vector_repository import (
    VectorRepository,
    UserContext,
    SearchResult,
)

from haystack_interface.access import can_access
from haystack_interface.config import HaystackSettings, load_settings

# Union rộng trước access-filter post-retrieval: lấy nhiều ứng viên hơn top_k để
# giảm rủi ro filter cắt mất kết quả hợp lệ (search.md cảnh báo post-filter).
_UNION_FACTOR = 5


class InMemoryVectorRepository(VectorRepository):
    def __init__(self, settings: HaystackSettings | None = None):
        self._s = settings or load_settings()
        self._store = InMemoryDocumentStore(
            embedding_similarity_function="cosine",
            index=self._s.index_id(),  # index id encode dimension
        )
        self._pipe = self._build_pipeline()

    def _build_pipeline(self) -> Pipeline:
        pipe = Pipeline()
        pipe.add_component("bm25", InMemoryBM25Retriever(self._store))
        pipe.add_component("embedding", InMemoryEmbeddingRetriever(self._store))
        pipe.add_component(
            "rrf",
            DocumentJoiner(join_mode="reciprocal_rank_fusion", sort_by_score=True),
        )
        pipe.connect("bm25.documents", "rrf.documents")
        pipe.connect("embedding.documents", "rrf.documents")
        return pipe

    # --- port methods ------------------------------------------------------ #
    async def upsert(self, chunk_id: str, vector: List[float], payload: dict) -> None:
        if len(vector) != self._s.embed_dimension:
            raise ValueError(
                f"Sai dimension: vector={len(vector)} != index={self._s.embed_dimension}. "
                "Đổi dimension là migration, không phải config edit (ingestion.md §8)."
            )
        # BM25 chạy trên full content (bm25_text) để bù caption-only (search.md §4).
        bm25_text = payload.get("bm25_text") or payload.get("child_text", "")
        meta = {k: v for k, v in payload.items() if k not in ("child_text", "bm25_text")}
        meta["child_text"] = payload.get("child_text", "")
        doc = Document(id=chunk_id, content=bm25_text, embedding=vector, meta=meta)
        # OVERWRITE => upsert idempotent theo id deterministic (write-order §7).
        await asyncio.to_thread(
            self._store.write_documents, [doc], DuplicatePolicy.OVERWRITE
        )

    async def hybrid_search(
        self,
        vector: List[float],
        query_text: str,
        user_context: UserContext,
        top_k: int = 20,
    ) -> List[SearchResult]:
        result = await asyncio.to_thread(
            self._pipe.run,
            {
                "bm25": {"query": query_text, "top_k": top_k},
                "embedding": {"query_embedding": vector, "top_k": top_k},
                "rrf": {"top_k": top_k * _UNION_FACTOR},
            },
        )
        docs: List[Document] = result["rrf"]["documents"]
        out: List[SearchResult] = []
        for doc in docs:
            if not can_access(doc.meta, user_context):
                continue
            out.append(self._to_result(doc))
            if len(out) >= top_k:
                break
        return out

    async def delete_by_document(self, document_id: str) -> None:
        ids = [
            d.id
            for d in self._store.filter_documents(
                {"field": "meta.document_id", "operator": "==", "value": document_id}
            )
        ]
        if ids:
            await asyncio.to_thread(self._store.delete_documents, ids)

    # --- helpers ----------------------------------------------------------- #
    @staticmethod
    def _to_result(doc: Document) -> SearchResult:
        m = doc.meta
        return SearchResult(
            chunk_id=doc.id,
            parent_id=m.get("parent_id", ""),
            document_id=m.get("document_id", ""),
            document_name=m.get("document_name", ""),
            file_type=m.get("file_type", ""),
            page_number=int(m.get("page_number", 0)),
            section_title=m.get("section_title", ""),
            child_text=m.get("child_text", doc.content or ""),
            parent_text=m.get("parent_text", ""),
            score=float(doc.score) if doc.score is not None else 0.0,  # RRF score
            rerank_score=float(m.get("rerank_score", 0.0)),
        )

    @property
    def store(self) -> InMemoryDocumentStore:
        return self._store
