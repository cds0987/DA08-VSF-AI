"""HaystackRagEngine — orchestrate ingest + search end-to-end.

Façade ghép port `EmbeddingService` + `VectorRepository` + chunking + reranker +
(optional) captioner thành đúng hai pipeline use-case của rag-service:

- ingest  ↔ application/use_cases/ingestion/... (split → caption/embed → upsert)
- search  ↔ application/use_cases/query/retrieval.py (embed → hybrid → rerank Top-k)

Engine KHÔNG biết SDK/provider/S3 — mọi AI đi qua port (embedder/captioner/reranker)
đã được composition root (factory) wire. Đổi backend = đổi wiring, không sửa engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from app.domain.repositories.embedding_service import EmbeddingService
from app.domain.repositories.vector_repository import (
    UserContext,
    SearchResult,
    VectorRepository,
)

from haystack_interface.caption import Captioner
from haystack_interface.chunking import split_sections
from haystack_interface.config import HaystackSettings, load_settings
from haystack_interface.rerank import Reranker


@dataclass
class IngestInput:
    document_id: str
    document_name: str
    file_type: str                       # pdf, docx, txt, md, ...
    markdown: str                        # canonical artifact (đã parse, ingestion.md §4)
    classification: str = "internal"     # public | internal | secret | top_secret
    allowed_departments: Optional[List[str]] = None
    allowed_user_ids: Optional[List[str]] = None


class HaystackRagEngine:
    def __init__(
        self,
        settings: HaystackSettings,
        embedder: EmbeddingService,
        vectors: VectorRepository,
        reranker: Reranker,
        captioner: Optional[Captioner] = None,
    ):
        self.settings = settings or load_settings()
        self.embedder = embedder
        self.vectors = vectors
        self.reranker = reranker
        # captioner=None => baseline: embed thẳng child (eval D7).
        # captioner set  => flow chuẩn: embed *caption* của section (ingestion.md §6).
        self.captioner = captioner

    # ------------------------------------------------------------------ #
    # INGEST (split → caption/embed → upsert)                            #
    # ------------------------------------------------------------------ #
    async def ingest(self, doc: IngestInput) -> int:
        s = self.settings
        sections = split_sections(
            doc.markdown,
            parent_max_words=s.parent_max_words,
            child_max_words=s.child_max_words,
            child_overlap_words=s.child_overlap_words,
        )

        chunk_ids: List[str] = []
        embed_texts: List[str] = []
        payloads: List[dict] = []
        for pi, section in enumerate(sections):
            parent_id = f"{doc.document_id}::p{pi}"

            if self.captioner is not None:
                # Flow chuẩn: 1 unit/section, embed *caption*; BM25 trên full content.
                caption = await self.captioner.caption(section.parent_text)
                units = [(f"{parent_id}::c0", caption, caption, section.parent_text)]
            else:
                # Baseline: embed thẳng child; BM25 cũng trên child.
                units = [
                    (f"{parent_id}::c{ci}", child, child, child)
                    for ci, child in enumerate(section.children)
                ]

            for chunk_id, to_embed, child_text, bm25_text in units:
                chunk_ids.append(chunk_id)
                embed_texts.append(to_embed)
                payloads.append(
                    {
                        "child_text": child_text,
                        "bm25_text": bm25_text,
                        "parent_id": parent_id,
                        "parent_text": section.parent_text,
                        "document_id": doc.document_id,
                        "document_name": doc.document_name,
                        "file_type": doc.file_type,
                        "page_number": section.page_number,
                        "section_title": section.section_title,
                        "classification": doc.classification,
                        "allowed_departments": doc.allowed_departments or [],
                        "allowed_user_ids": doc.allowed_user_ids or [],
                    }
                )

        if not chunk_ids:
            return 0

        # embed_batch -> vectors (cùng embedder cho ingest+query).
        vectors = await self.embedder.embed_batch(embed_texts)
        # upsert vào vector store (payload mang parent_text + metadata).
        for chunk_id, vector, payload in zip(chunk_ids, vectors, payloads):
            await self.vectors.upsert(chunk_id, vector, payload)
        return len(chunk_ids)

    # ------------------------------------------------------------------ #
    # SEARCH (embed → hybrid → rerank Top-k)                             #
    # ------------------------------------------------------------------ #
    async def search(
        self,
        query_text: str,
        user_context: UserContext,
        top_k: Optional[int] = None,
        rerank_threshold: Optional[float] = None,
    ) -> List[SearchResult]:
        s = self.settings
        k = top_k if top_k is not None else s.rerank_top_k
        th = rerank_threshold if rerank_threshold is not None else s.rerank_threshold

        # 1. embed query (CÙNG embedder với ingest)
        qvec = await self.embedder.embed(query_text)
        # 2. hybrid_search (vector + BM25 RRF) -> candidates
        candidates = await self.vectors.hybrid_search(
            qvec, query_text, user_context, top_k=s.top_k_candidates
        )
        # 3. rerank (FULL content) + lọc threshold + trả Top-k
        return await self.reranker.rerank(query_text, candidates, top_k=k, threshold=th)
