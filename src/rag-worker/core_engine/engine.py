"""HaystackRagEngine orchestrates ingest end-to-end."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import os
from typing import List, Optional
from uuid import uuid4

from core_engine.caption import Captioner
from core_engine.chunking import Chunker, SectionChunker
from core_engine.config import HaystackSettings, load_settings
from core_engine.logging_utils import Stopwatch, log_event
from core_engine.types import EmbeddingService, VectorRepository
from core_engine.vectorstore.types import VectorRecord


class ChunkLimitExceededError(ValueError):
    """Document expands into too many chunks for safe ingestion."""


class CaptionFallbackThresholdExceededError(RuntimeError):
    """Too many caption fallbacks indicate degraded AI quality for this document."""


@dataclass
class IngestInput:
    document_id: str
    document_name: str
    file_type: str
    markdown: str
    source_uri: Optional[str] = None
    artifact_uri: Optional[str] = None
    correlation_id: Optional[str] = None
    trace_handle: object | None = None


class HaystackRagEngine:
    def __init__(
        self,
        settings: HaystackSettings,
        embedder: EmbeddingService,
        vectors: VectorRepository,
        captioner: Optional[Captioner] = None,
        chunker: Chunker | None = None,
        tracer: object | None = None,
    ):
        self.settings = settings or load_settings()
        self.embedder = embedder
        self.vectors = vectors
        self.captioner = captioner
        self._tracer = tracer
        self.chunker = chunker or SectionChunker(
            parent_max_words=self.settings.parent_max_words,
            child_max_words=self.settings.child_max_words,
            child_overlap_words=self.settings.child_overlap_words,
        )
        self._logger = logging.getLogger(__name__)
        self._caption_semaphore = asyncio.Semaphore(
            max(1, int(os.getenv("CAPTION_MAX_CONCURRENCY", "5")))
        )
        self._max_chunks_per_doc = max(1, int(os.getenv("MAX_CHUNKS_PER_DOC", "50000")))
        self._caption_fallback_threshold = min(
            1.0,
            max(0.0, float(os.getenv("CAPTION_FALLBACK_THRESHOLD", "0.3"))),
        )

    def _span_start(self, trace: object | None, name: str, payload: dict) -> object | None:
        if self._tracer is None:
            return None
        try:
            return self._tracer.span_start(trace, name, payload)
        except Exception:
            return None

    def _span_ok(self, span: object | None, payload: dict) -> None:
        if self._tracer is None:
            return
        with contextlib.suppress(Exception):
            self._tracer.span_ok(span, payload)

    def _span_error(self, span: object | None, exc: BaseException) -> None:
        if self._tracer is None:
            return
        with contextlib.suppress(Exception):
            self._tracer.span_error(span, exc)

    def _generation(
        self,
        trace: object | None,
        *,
        name: str,
        model: str,
        start_time: datetime,
        input_data: dict,
        output: dict,
        metadata: dict,
    ) -> None:
        if self._tracer is None:
            return
        with contextlib.suppress(Exception):
            self._tracer.generation(
                trace,
                name=name,
                model=model,
                start_time=start_time,
                input_data=input_data,
                output=output,
                metadata=metadata,
            )

    def _safe_model(self, component: object | None, capability: str, fallback: str) -> str:
        with contextlib.suppress(Exception):
            provider = getattr(component, "_provider", None)
            if provider is None or not hasattr(provider, "cap"):
                return fallback
            config = provider.cap(capability)
            model = getattr(config, "model", "")
            if isinstance(model, str) and model.strip():
                return model
        return fallback

    def _safe_collection_name(self) -> str:
        with contextlib.suppress(Exception):
            config = getattr(self.vectors, "config", None)
            if config is None or not hasattr(config, "index_id"):
                return ""
            name = config.index_id()
            if isinstance(name, str):
                return name
        return ""

    async def ingest(self, doc: IngestInput) -> int:
        request_correlation_id = doc.correlation_id or str(uuid4())
        total_sw = Stopwatch()
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
        trace = getattr(doc, "trace_handle", None)
        split_span = self._span_start(
            trace,
            "chunk",
            {"chars": len(doc.markdown or ""), "source_uri": source_uri},
        )
        split_sw = Stopwatch()
        try:
            sections = self.chunker.split(doc.markdown)
        except Exception as exc:
            self._span_error(split_span, exc)
            raise
        split_ms = split_sw.elapsed_ms()
        self._span_ok(
            split_span,
            {
                "num_sections": len(sections),
                "num_chunks": sum(len(section.children) for section in sections),
            },
        )
        caption_ms = 0.0
        caption_fallbacks = 0
        total_children = sum(len(section.children) for section in sections)

        chunk_ids: List[str] = []
        embed_texts: List[str] = []
        payloads: List[dict] = []
        captions_by_index: dict[int, str] = {}
        if total_children > self._max_chunks_per_doc:
            raise ChunkLimitExceededError(
                f"document {doc.document_id} produced {total_children} chunks > "
                f"MAX_CHUNKS_PER_DOC ({self._max_chunks_per_doc})"
            )
        if self.captioner is not None and sections:
            async def _caption_one(index: int, text: str) -> tuple[int, str, bool]:
                async with self._caption_semaphore:
                    if hasattr(self.captioner, "caption_with_metadata"):
                        result = await self.captioner.caption_with_metadata(text)  # type: ignore[attr-defined]
                        return index, result.text, result.used_fallback
                    caption = await self.captioner.caption(text)
                    return index, caption, False

            caption_start = datetime.now(timezone.utc)
            caption_span = self._span_start(
                trace,
                "caption",
                {"sections": len(sections), "max_chars": max(len(section.parent_text) for section in sections)},
            )
            caption_sw = Stopwatch()
            try:
                caption_results = await asyncio.gather(
                    *[_caption_one(index, section.parent_text) for index, section in enumerate(sections)]
                )
            except Exception as exc:
                self._span_error(caption_span, exc)
                raise
            caption_ms = caption_sw.elapsed_ms()
            for index, caption, used_fallback in caption_results:
                captions_by_index[index] = caption
                if used_fallback:
                    caption_fallbacks += 1
            self._generation(
                trace,
                name="caption",
                model=self._safe_model(self.captioner, "caption", "caption"),
                start_time=caption_start,
                input_data={"sections": len(sections)},
                output={"captions": len(caption_results), "fallback_count": caption_fallbacks},
                metadata={"stage": "caption"},
            )
            self._span_ok(
                caption_span,
                {
                    "sections": len(sections),
                    "fallback_count": caption_fallbacks,
                },
            )

        for parent_index, section in enumerate(sections):
            parent_id = f"{doc.document_id}::p{parent_index}"
            heading_path = [section.section_title] if section.section_title else []

            if self.captioner is not None:
                caption = captions_by_index[parent_index]
                units = [
                    (f"{parent_id}::c{child_index}", caption, caption, child)
                    for child_index, child in enumerate(section.children)
                ]
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
                        "page_number": section.section_index,
                        "section_title": section.section_title,
                        "heading_path": heading_path,
                        "caption": caption,
                        "source_uri": source_uri,
                        "artifact_uri": artifact_uri,
                    }
                )

        existing_chunk_ids = set(await self.vectors.list_chunk_ids_by_document(doc.document_id))
        if not chunk_ids:
            if existing_chunk_ids:
                await self.vectors.delete_many(sorted(existing_chunk_ids))
            log_event(
                self._logger,
                logging.INFO,
                "ingest_skipped_empty",
                stage="ingest",
                correlation_id=request_correlation_id,
                document_id=doc.document_id,
            )
            return 0
        if self.captioner is not None and sections:
            fallback_rate = float(caption_fallbacks) / float(len(sections))
            if fallback_rate > self._caption_fallback_threshold:
                raise CaptionFallbackThresholdExceededError(
                    f"caption fallback rate {fallback_rate:.3f} exceeded threshold "
                    f"{self._caption_fallback_threshold:.3f}"
                )

        embed_span = self._span_start(
            trace,
            "embed",
            {"chunks": len(embed_texts), "dimension": settings.embed_dimension},
        )
        embed_start = datetime.now(timezone.utc)
        embed_sw = Stopwatch()
        try:
            vectors = await self.embedder.embed_batch(embed_texts)
        except Exception as exc:
            self._span_error(embed_span, exc)
            raise
        embed_ms = embed_sw.elapsed_ms()
        self._generation(
            trace,
            name="embed",
            model=self._safe_model(self.embedder, "embed", "embed"),
            start_time=embed_start,
            input_data={"chunks": len(embed_texts)},
            output={"vectors": len(vectors), "dimension": settings.embed_dimension},
            metadata={"stage": "embed", "dimension": settings.embed_dimension},
        )
        self._span_ok(
            embed_span,
            {"vectors": len(vectors), "dimension": settings.embed_dimension},
        )
        records = [
            VectorRecord(chunk_id=chunk_id, vector=vector, payload=payload)
            for chunk_id, vector, payload in zip(chunk_ids, vectors, payloads)
        ]
        write_span = self._span_start(
            trace,
            "qdrant-write",
            {
                "collection": self._safe_collection_name(),
                "num_vectors": len(records),
            },
        )
        write_sw = Stopwatch()
        try:
            await self.vectors.upsert_many(records)
            stale_chunk_ids = sorted(existing_chunk_ids - set(chunk_ids))
            if stale_chunk_ids:
                await self.vectors.delete_many(stale_chunk_ids)
        except Exception as exc:
            self._span_error(write_span, exc)
            raise
        write_ms = write_sw.elapsed_ms()
        self._span_ok(
            write_span,
            {
                "upserted": len(records),
                "pruned_chunk_count": len(stale_chunk_ids),
            },
        )
        log_event(
            self._logger,
            logging.INFO,
            "ingest_completed",
            stage="ingest",
            correlation_id=request_correlation_id,
            document_id=doc.document_id,
            chunk_count=len(chunk_ids),
            pruned_chunk_count=len(stale_chunk_ids),
            split_ms=split_ms,
            caption_ms=round(caption_ms, 3),
            caption_fallback_count=caption_fallbacks,
            embed_ms=embed_ms,
            vector_write_ms=write_ms,
            total_ms=total_sw.elapsed_ms(),
        )
        return len(chunk_ids)
