"""HaystackRagEngine orchestrates ingest + search end-to-end."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import List, Optional
from uuid import uuid4

from app.domain.repositories.embedding_service import EmbeddingService
from app.domain.repositories.vector_repository import SearchResult, VectorRepository

from core_engine.caption import Captioner
from core_engine.chunking import split_sections
from core_engine.config import HaystackSettings, load_settings
from core_engine.logging_utils import log_event
from core_engine.rerank import Reranker
from core_engine.vectorstore.types import VectorRecord


@dataclass
class IngestInput:
    document_id: str
    document_name: str
    file_type: str
    markdown: str
    source_uri: Optional[str] = None
    artifact_uri: Optional[str] = None
    correlation_id: Optional[str] = None


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
        self._logger = logging.getLogger(__name__)

    async def ingest(self, doc: IngestInput) -> int:
        request_correlation_id = doc.correlation_id or str(uuid4())
        log_event(
            self._logger,
            logging.INFO,
            "ingest_started",
            stage="ingest",
            correlation_id=request_correlation_id,
            document_id=doc.document_id,
            document_name=doc.document_name,
        )
        settings = self.settings
        source_uri = doc.source_uri or f"local://{doc.document_id}"
        artifact_uri = doc.artifact_uri or f"{source_uri}#artifact"
        sections = split_sections(
            doc.markdown,
            parent_max_words=settings.parent_max_words,
            child_max_words=settings.child_max_words,
            child_overlap_words=settings.child_overlap_words,
        )

        chunk_ids: List[str] = []
        embed_texts: List[str] = []
        payloads: List[dict] = []
        for parent_index, section in enumerate(sections):
            parent_id = f"{doc.document_id}::p{parent_index}"
            heading_path = [section.section_title] if section.section_title else []

            if self.captioner is not None:
                caption = await self.captioner.caption(section.parent_text)
                units = [(f"{parent_id}::c0", caption, caption, section.parent_text)]
            else:
                units = [
                    (f"{parent_id}::c{child_index}", child, child, child)
                    for child_index, child in enumerate(section.children)
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
            log_event(
                self._logger,
                logging.INFO,
                "ingest_skipped_empty",
                stage="ingest",
                correlation_id=request_correlation_id,
                document_id=doc.document_id,
            )
            return 0

        existing_chunk_ids = set(await self.vectors.list_chunk_ids_by_document(doc.document_id))
        vectors = await self.embedder.embed_batch(embed_texts)
        records = [
            VectorRecord(chunk_id=chunk_id, vector=vector, payload=payload)
            for chunk_id, vector, payload in zip(chunk_ids, vectors, payloads)
        ]
        await self.vectors.upsert_many(records)
        stale_chunk_ids = sorted(existing_chunk_ids - set(chunk_ids))
        if stale_chunk_ids:
            await self.vectors.delete_many(stale_chunk_ids)
        log_event(
            self._logger,
            logging.INFO,
            "ingest_completed",
            stage="ingest",
            correlation_id=request_correlation_id,
            document_id=doc.document_id,
            chunk_count=len(chunk_ids),
            pruned_chunk_count=len(stale_chunk_ids),
        )
        return len(chunk_ids)

    async def search(
        self,
        query_text: str,
        top_k: Optional[int] = None,
        rerank_threshold: Optional[float] = None,
        correlation_id: Optional[str] = None,
    ) -> List[SearchResult]:
        settings = self.settings
        effective_top_k = top_k if top_k is not None else settings.rerank_top_k
        threshold = (
            rerank_threshold if rerank_threshold is not None else settings.rerank_threshold
        )
        request_correlation_id = correlation_id or str(uuid4())
        log_event(
            self._logger,
            logging.INFO,
            "search_started",
            stage="search",
            correlation_id=request_correlation_id,
            top_k=effective_top_k,
            rerank_threshold=threshold,
        )

        query_vector = await self.embedder.embed(query_text)
        candidates = await self.vectors.hybrid_search(
            query_vector,
            query_text,
            top_k=settings.top_k_candidates,
        )
        results = await self.reranker.rerank(
            query_text,
            candidates,
            top_k=effective_top_k,
            threshold=threshold,
        )
        for result in results:
            result.correlation_id = request_correlation_id
        log_event(
            self._logger,
            logging.INFO,
            "search_completed",
            stage="search",
            correlation_id=request_correlation_id,
            candidate_count=len(candidates),
            result_count=len(results),
        )
        return results
