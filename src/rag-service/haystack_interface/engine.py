"""HaystackRagEngine orchestrates ingest + search end-to-end."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
from uuid import uuid4

from app.domain.repositories.embedding_service import EmbeddingService
from app.domain.repositories.vector_repository import SearchResult, VectorRepository

from haystack_interface.caption import Captioner
from haystack_interface.chunking import split_sections
from haystack_interface.config import HaystackSettings, load_settings
from haystack_interface.rerank import Reranker


@dataclass
class IngestInput:
    document_id: str
    document_name: str
    file_type: str
    markdown: str
    source_uri: Optional[str] = None
    artifact_uri: Optional[str] = None


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
        self.captioner = captioner

    async def ingest(self, doc: IngestInput) -> int:
        s = self.settings
        source_uri = doc.source_uri or f"local://{doc.document_id}"
        artifact_uri = doc.artifact_uri or f"{source_uri}#artifact"
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
            heading_path = [section.section_title] if section.section_title else []

            if self.captioner is not None:
                caption = await self.captioner.caption(section.parent_text)
                units = [(f"{parent_id}::c0", caption, caption, section.parent_text)]
            else:
                units = [
                    (f"{parent_id}::c{ci}", child, child, child)
                    for ci, child in enumerate(section.children)
                ]

            for chunk_id, to_embed, caption, bm25_text in units:
                chunk_ids.append(chunk_id)
                embed_texts.append(to_embed)
                payloads.append(
                    {
                        "child_text": caption,
                        "bm25_text": bm25_text,
                        "parent_id": parent_id,
                        "parent_text": section.parent_text,
                        "document_id": doc.document_id,
                        "document_name": doc.document_name,
                        "file_type": doc.file_type,
                        "page_number": section.page_number,
                        "section_title": section.section_title,
                        "heading_path": heading_path,
                        "caption": caption,
                        "source_uri": source_uri,
                        "artifact_uri": artifact_uri,
                    }
                )

        if not chunk_ids:
            return 0

        vectors = await self.embedder.embed_batch(embed_texts)
        for chunk_id, vector, payload in zip(chunk_ids, vectors, payloads):
            await self.vectors.upsert(chunk_id, vector, payload)
        return len(chunk_ids)

    async def search(
        self,
        query_text: str,
        top_k: Optional[int] = None,
        rerank_threshold: Optional[float] = None,
        correlation_id: Optional[str] = None,
    ) -> List[SearchResult]:
        s = self.settings
        k = top_k if top_k is not None else s.rerank_top_k
        th = rerank_threshold if rerank_threshold is not None else s.rerank_threshold
        request_correlation_id = correlation_id or str(uuid4())

        qvec = await self.embedder.embed(query_text)
        candidates = await self.vectors.hybrid_search(
            qvec, query_text, top_k=s.top_k_candidates
        )
        results = await self.reranker.rerank(query_text, candidates, top_k=k, threshold=th)
        for result in results:
            result.correlation_id = request_correlation_id
        return results
