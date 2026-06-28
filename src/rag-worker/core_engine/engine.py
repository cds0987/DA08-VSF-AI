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


def _context_header(document_name: str, section_title: str) -> str:
    """Lineage tài liệu chèn vào text embed/bm25 (Contextual Retrieval): tên tài liệu = tín
    hiệu phân biệt giữa các document gần-trùng; mục = ngữ cảnh section. Cả 2 rỗng -> "" (no-op)."""
    doc = (document_name or "").strip()
    sec = (section_title or "").strip()
    parts = [p for p in (doc, sec) if p]
    return f"[Tài liệu: {' | Mục: '.join(parts)}]" if parts else ""


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
        embed_targets: list | None = None,
        shard_mode: bool = False,
    ):
        self.settings = settings or load_settings()
        self.embedder = embedder
        self.vectors = vectors
        # Multi-collection: tập đích SECONDARY (model khác -> collection khác). Mỗi đích
        # tự embed CÙNG chunks + upsert collection riêng. Rỗng -> hành vi cũ (1 collection).
        # Tách parse/OCR/caption (làm 1 lần ở đây) khỏi embed -> chia sẻ chunks cho mọi model.
        self.embed_targets = list(embed_targets or [])
        # SHARD N/5: khi bật, mỗi doc ghi vào CHỈ 1 collection (round-robin hash theo
        # document_id) thay vì replicate cả pool -> embed throughput ×len(pool). Pool ghi =
        # [primary] + embed_targets (slot 0 = primary self.embedder/self.vectors). mode=False
        # (mặc định) -> hành vi replicate cũ (primary LUÔN ghi + mọi secondary). Xem
        # core_engine.multi_embed.select_shard_index.
        self.shard_mode = bool(shard_mode)
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

    def _embed_text_for(self, caption: str | None, child: str) -> str:
        """Text đưa vào embedding dense, theo settings.embed_target.

        captioner tắt -> chỉ raw. Bật -> caption_raw (mặc định, caption + raw để
        giữ literal cho retrieve), caption (cũ), hoặc raw.
        """
        if caption is None:
            return child
        target = getattr(self.settings, "embed_target", "caption_raw")
        if target == "caption":
            return caption
        if target == "raw":
            return child
        return f"{caption}\n\n{child}"

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

    async def _write_one_target(
        self,
        target: object,
        chunk_ids: List[str],
        embed_texts: List[str],
        payloads: List[dict],
        existing_chunk_ids: set,
    ) -> None:
        """Embed embed_texts bằng embedder của target -> upsert vào vectors của target.

        Mỗi target = 1 model + 1 collection độc lập. Prune stale chunk như primary (giữ
        collection đồng bộ document). Vỡ ở đây KHÔNG ảnh hưởng primary/target khác (caller
        gather return_exceptions)."""
        vectors = await target.embedder.embed_batch(embed_texts)
        records = [
            VectorRecord(chunk_id=chunk_id, vector=vector, payload=payload)
            for chunk_id, vector, payload in zip(chunk_ids, vectors, payloads)
        ]
        existing_target = set(
            await target.vectors.list_chunk_ids_by_document(payloads[0]["document_id"])
        ) if payloads else set(existing_chunk_ids)
        await target.vectors.upsert_many(records)
        stale = sorted(existing_target - set(chunk_ids))
        if stale:
            await target.vectors.delete_many(stale)

    async def _write_secondary_targets(
        self,
        chunk_ids: List[str],
        embed_texts: List[str],
        payloads: List[dict],
        existing_chunk_ids: set,
        trace: object | None,
        *,
        correlation_id: str,
        document_id: str,
        targets: list | None = None,
    ) -> None:
        # targets=None -> mọi embed_targets (replicate). Shard truyền danh sách 1-phần-tử
        # (chỉ collection của slot đã chọn).
        targets = list(self.embed_targets if targets is None else targets)
        span = self._span_start(
            trace,
            "multi-embed",
            {"targets": len(targets), "chunks": len(embed_texts)},
        )
        results = await asyncio.gather(
            *[
                self._write_one_target(t, chunk_ids, embed_texts, payloads, existing_chunk_ids)
                for t in targets
            ],
            return_exceptions=True,
        )
        ok, failed = 0, 0
        for target, result in zip(targets, results):
            if isinstance(result, BaseException):
                failed += 1
                log_event(
                    self._logger,
                    logging.WARNING,
                    "multi_embed_target_failed",
                    stage="multi-embed",
                    correlation_id=correlation_id,
                    document_id=document_id,
                    embed_model=getattr(target, "embed_model", "?"),
                    collection=getattr(getattr(target, "config", None), "index_id", lambda: "")(),
                    error_type=type(result).__name__,
                    error=str(result)[:300],
                )
            else:
                ok += 1
        self._span_ok(span, {"ok": ok, "failed": failed})

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
            # Đưa NỘI DUNG THẬT vào trace để thấy "AI trả gì": input = đoạn text/ảnh
            # đưa vào captioner, output = caption/OCR AI sinh ra. Cắt ngắn + cap số đoạn
            # để trace không phình (vd PDF vài trăm chunk).
            _cap_sample, _cap_chars = 8, 600
            _n = min(_cap_sample, len(sections))
            self._generation(
                trace,
                name="caption",
                model=self._safe_model(self.captioner, "caption", "caption"),
                start_time=caption_start,
                input_data={
                    "sections": len(sections),
                    "input_texts": [sections[i].parent_text[:_cap_chars] for i in range(_n)],
                },
                output={
                    "captions": len(caption_results),
                    "fallback_count": caption_fallbacks,
                    "caption_texts": [(captions_by_index.get(i) or "")[:_cap_chars] for i in range(_n)],
                },
                metadata={"stage": "caption", "sample_shown": _n, "truncated_to_chars": _cap_chars},
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
            # Section không có heading thật -> heading_path RỖNG (UI đã hiển thị tên tài
            # liệu riêng; nhồi document_name vào đây gây trùng tên ở citation). section_title
            # metadata fallback về document_name cho dễ trace, KHÔNG ảnh hưởng UI.
            has_heading = bool(section.section_title) and section.section_title != "(no heading)"
            heading_path = [section.section_title] if has_heading else []

            # Contextual Retrieval: mọi chunk MANG LINEAGE tài liệu (tên tài liệu + mục) trong
            # text được EMBED (dense) + BM25 (sparse) -> phân biệt chunk gần-trùng giữa các
            # document (vd bảng per-diem giống nhau ở nhiều tài liệu; chunk-từ-ảnh vốn chỉ có
            # dãy số, không tự mang danh tính tài liệu). KHÔNG đổi payload schema: child_text/
            # caption giữ nguyên raw; chỉ enrich biểu diễn searchable.
            ctx_header = _context_header(doc.document_name, section.section_title if has_heading else "")

            caption = (
                captions_by_index[parent_index] if self.captioner is not None else None
            )

            for child_index, child in enumerate(section.children):
                chunk_id = f"{parent_id}::c{child_index}"
                # caption hiển thị: có captioner -> caption AI; không -> chính raw child.
                display_caption = caption if caption is not None else child
                chunk_ids.append(chunk_id)
                # Vector dense embed THEO embed_target (caption_raw mặc định -> giữ literal),
                # CỘNG context-header lên đầu -> dense vector mã hoá danh tính tài liệu.
                embed_texts.append(f"{ctx_header}\n{self._embed_text_for(caption, child)}")
                payloads.append(
                    {
                        # child_text LUÔN = raw child (trước đây nhầm = caption -> chunk
                        # text bị thay bằng tóm tắt AI). caption giữ riêng ở field "caption".
                        "child_text": child,
                        # bm25_text = context-header + (section_title) + child. child VẪN là
                        # substring (test gác) -> sparse khớp cả tên tài liệu lẫn nội dung.
                        "bm25_text": (f"{ctx_header} {section.section_title} {child}"
                                      if has_heading else f"{ctx_header} {child}"),
                        "parent_id": parent_id,
                        "parent_text": section.parent_text,
                        "document_id": doc.document_id,
                        "document_name": doc.document_name,
                        "file_type": doc.file_type,
                        "page_number": section.section_index,
                        "section_title": section.section_title if has_heading else doc.document_name,
                        "heading_path": heading_path,
                        "caption": display_caption,
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

        # ── SHARD selection ──────────────────────────────────────────────────
        # Pool ghi = [primary] + embed_targets. shard_mode -> chọn 1 slot deterministic
        # theo hash(document_id); slot 0 = primary. write_primary = (slot==0). Secondary
        # được ghi = chỉ target ở slot đã chọn (nếu !=0). replicate -> primary + tất cả.
        write_primary = True
        selected_secondaries = list(self.embed_targets)
        shard_slot = -1
        if self.shard_mode:
            from core_engine.multi_embed import select_shard_index

            pool_size = 1 + len(self.embed_targets)
            shard_slot = select_shard_index(doc.document_id, pool_size)
            write_primary = shard_slot == 0
            selected_secondaries = (
                [self.embed_targets[shard_slot - 1]] if shard_slot >= 1 else []
            )
            log_event(
                self._logger,
                logging.INFO,
                "shard_route_selected",
                stage="ingest",
                correlation_id=request_correlation_id,
                document_id=doc.document_id,
                shard_slot=shard_slot,
                pool_size=pool_size,
                collection=(
                    self._safe_collection_name()
                    if write_primary
                    else getattr(getattr(selected_secondaries[0], "config", None), "index_id", lambda: "")()
                ),
            )
            if not write_primary:
                # Doc KHÔNG thuộc shard primary: dọn vector cũ ở collection primary nếu có
                # (vd re-ingest sau khi đổi pool) để collection primary không giữ bản mồ côi.
                if existing_chunk_ids:
                    await self.vectors.delete_many(sorted(existing_chunk_ids))

        if not write_primary:
            # Primary KHÔNG nhận doc này (shard): bỏ qua embed+write primary, chỉ ghi
            # secondary đã chọn. Trả về số chunk đã produce (đo throughput nhất quán).
            stale_chunk_ids: List[str] = []
            await self._write_secondary_targets(
                chunk_ids, embed_texts, payloads, existing_chunk_ids, trace,
                correlation_id=request_correlation_id, document_id=doc.document_id,
                targets=selected_secondaries,
            )
            log_event(
                self._logger,
                logging.INFO,
                "ingest_completed",
                stage="ingest",
                correlation_id=request_correlation_id,
                document_id=doc.document_id,
                chunk_count=len(chunk_ids),
                pruned_chunk_count=0,
                split_ms=split_ms,
                caption_ms=round(caption_ms, 3),
                caption_fallback_count=caption_fallbacks,
                shard_slot=shard_slot,
                total_ms=total_sw.elapsed_ms(),
            )
            return len(chunk_ids)

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
            VectorRecord(
                chunk_id=chunk_id,
                vector=vector,
                payload=payload,
            )
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
        # ── MULTI-COLLECTION: embed CÙNG chunks bằng mọi model secondary -> upsert
        # collection riêng (index_id per model). CHIA SẺ embed_texts/payloads/chunk_ids
        # đã tính 1 lần (parse/OCR/caption KHÔNG lặp). Fault-isolated: 1 model fail KHÔNG
        # vỡ primary (đã commit ở trên) lẫn model khác (gather return_exceptions).
        # replicate -> selected_secondaries = mọi embed_targets. shard slot==0 (primary) ->
        # selected_secondaries = [] (doc chỉ thuộc primary). slot>=1 đã return sớm ở trên.
        if selected_secondaries:
            await self._write_secondary_targets(
                chunk_ids, embed_texts, payloads, existing_chunk_ids, trace,
                correlation_id=request_correlation_id, document_id=doc.document_id,
                targets=selected_secondaries,
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
