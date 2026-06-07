from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.entities.document import Document, DocumentStatus
from app.domain.entities.ingest_job import IngestJob, IngestJobStatus
from app.domain.entities.job_log import JobLog
from app.domain.repositories.artifact_store import ArtifactStore
from app.domain.repositories.document_repository import DocumentRepository
from app.domain.repositories.ingest_job_repository import IngestJobRepository
from app.domain.repositories.parser import Parser
from core_engine.engine import HaystackRagEngine, IngestInput
from core_engine.logging_utils import log_event


class EmptyIngestResultError(ValueError):
    """Raised when parsing/indexing produces no retrievable content."""


class IngestDocumentUseCase:
    def __init__(
        self,
        engine: HaystackRagEngine,
        document_repository: DocumentRepository,
        job_repository: IngestJobRepository,
        parser: Parser,
        artifact_store: ArtifactStore,
        *,
        claim_heartbeat_interval_seconds: float = 5.0,
    ):
        self._engine = engine
        self._documents = document_repository
        self._jobs = job_repository
        self._parser = parser
        self._artifact_store = artifact_store
        self._logger = logging.getLogger(__name__)
        self._claim_heartbeat_interval_seconds = claim_heartbeat_interval_seconds
        self._ingest_timeout_seconds = max(
            0.001, float(os.getenv("INGEST_JOB_TIMEOUT_SECONDS", "600"))
        )

    async def enqueue(
        self,
        *,
        document_id: str,
        document_name: str,
        file_type: str,
        markdown: str | None,
        source_uri: str | None = None,
        artifact_uri: str | None = None,
        correlation_id: str | None = None,
    ) -> IngestJob:
        if not markdown and not source_uri:
            raise ValueError("ingest requires either markdown or source_uri")
        request_correlation_id = correlation_id or f"ingest:{document_id}"
        # Dedup redelivery: NATS at-least-once có thể gửi lại doc.ingest. Nếu đã có
        # job chưa-terminal cho document_id, bỏ qua tạo job mới (tránh re-fetch S3 +
        # parse + embed dư thừa và hai worker chạy song song cùng doc).
        existing = await self._jobs.find_active_job(document_id)
        if existing is not None:
            log_event(
                self._logger,
                logging.INFO,
                "ingest_enqueue_skipped_duplicate",
                stage="queue",
                document_id=document_id,
                correlation_id=request_correlation_id,
                existing_job_id=existing.id,
                existing_status=existing.status.value,
            )
            return existing
        existing_document = await self._documents.get_by_id(document_id)
        if existing_document is not None and existing_document.status is DocumentStatus.COMPLETED:
            log_event(
                self._logger,
                logging.INFO,
                "ingest_enqueue_skipped_completed",
                stage="queue",
                document_id=document_id,
                correlation_id=request_correlation_id,
            )
            return IngestJob(
                id=f"completed:{document_id}",
                document_id=document_id,
                document_name=existing_document.name,
                file_type=existing_document.file_type,
                source_uri=source_uri,
                markdown=markdown,
                artifact_uri=artifact_uri,
                correlation_id=request_correlation_id,
                status=IngestJobStatus.COMPLETED,
                created_at=existing_document.created_at,
                updated_at=existing_document.created_at,
                chunk_count=existing_document.chunk_count,
            )
        if existing_document is not None and existing_document.status is DocumentStatus.DELETED:
            log_event(
                self._logger,
                logging.INFO,
                "ingest_enqueue_skipped_deleted",
                stage="queue",
                document_id=document_id,
                correlation_id=request_correlation_id,
            )
            return IngestJob(
                id=f"deleted:{document_id}",
                document_id=document_id,
                document_name=existing_document.name,
                file_type=existing_document.file_type,
                source_uri=source_uri,
                markdown=markdown,
                artifact_uri=artifact_uri,
                correlation_id=request_correlation_id,
                status=IngestJobStatus.FAILED,
                created_at=existing_document.created_at,
                updated_at=existing_document.created_at,
                error_message="document deleted",
            )
        now = datetime.now(UTC)
        await self._documents.create(
            Document(
                id=document_id,
                name=document_name,
                file_type=file_type,
                s3_key=source_uri or f"inline://{document_id}",
                status=DocumentStatus.QUEUED,
                created_at=now,
            )
        )
        job = IngestJob(
            id=str(uuid4()),
            document_id=document_id,
            document_name=document_name,
            file_type=file_type,
            source_uri=source_uri,
            markdown=markdown,
            artifact_uri=artifact_uri,
            correlation_id=request_correlation_id,
            status=IngestJobStatus.PENDING,
            created_at=now,
            updated_at=now,
        )
        try:
            await self._jobs.enqueue(job)
        except Exception:
            with contextlib.suppress(Exception):
                await self._documents.purge(document_id)
            raise
        await self._append_job_log(
            JobLog(
                document_id=document_id,
                correlation_id=request_correlation_id,
                stage="queue",
                status=IngestJobStatus.PENDING.value,
                created_at=now,
            )
        )
        return job

    async def process_next_job(self) -> IngestJob | None:
        claim_id = str(uuid4())
        job = await self._jobs.claim_next_pending(claim_id)
        if job is None:
            return None
        heartbeat_stop = asyncio.Event()
        await self._documents.update_status(job.document_id, DocumentStatus.PROCESSING)
        await self._append_job_log(
            JobLog(
                document_id=job.document_id,
                correlation_id=job.correlation_id,
                stage="ingest",
                status=DocumentStatus.PROCESSING.value,
                created_at=datetime.now(UTC),
            )
        )
        heartbeat_task = asyncio.create_task(
            self._maintain_claim_lease(job.id, claim_id, heartbeat_stop)
        )
        try:
            markdown, source_uri, artifact_uri = await self._prepare_markdown(job)
            chunk_count = await asyncio.wait_for(
                self._engine.ingest(
                    IngestInput(
                        document_id=job.document_id,
                        document_name=job.document_name,
                        file_type=job.file_type,
                        markdown=markdown,
                        source_uri=source_uri,
                        artifact_uri=artifact_uri,
                        correlation_id=job.correlation_id,
                    )
                ),
                timeout=self._ingest_timeout_seconds,
            )
            if chunk_count <= 0:
                raise EmptyIngestResultError(
                    "ingest produced 0 chunks; source is empty or OCR is required"
                )
        except Exception as exc:
            failed = await self._jobs.fail_job(job.id, claim_id, error_message=str(exc))
            if failed:
                await self._documents.update_status(
                    job.document_id,
                    DocumentStatus.FAILED,
                    error=str(exc),
                )
            await self._append_job_log(
                JobLog(
                    document_id=job.document_id,
                    correlation_id=job.correlation_id,
                    stage="ingest",
                    status=DocumentStatus.FAILED.value,
                    error_type=exc.__class__.__name__,
                    error_message=str(exc),
                    created_at=datetime.now(UTC),
                )
            )
            # KHÔNG raise: fail_job đã đặt FAILED terminal (retry do stale-reaper lo khi
            # worker CHẾT, không phải khi job lỗi). Trả job FAILED để worker publish
            # doc.status:failed (nếu raise thì nhánh except của worker nuốt job -> mất
            # status, contract vỡ). Job terminal nên không bị claim lại -> không busy-loop.
            return await self._jobs.get_job(job.id)
        finally:
            heartbeat_stop.set()
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
        document = await self._documents.get_by_id(job.document_id)
        if document is None or document.status is DocumentStatus.DELETED:
            await self._engine.vectors.delete_by_document(job.document_id)
            failed = await self._jobs.fail_job(
                job.id,
                claim_id,
                error_message="document deleted during ingest",
            )
            if failed:
                try:
                    await self._jobs.mark_status_published(job.id)
                except Exception as exc:  # noqa: BLE001 - deleted doc should not block cleanup
                    log_event(
                        self._logger,
                        logging.WARNING,
                        "ingest_deleted_document_mark_published_failed",
                        stage="ingest",
                        job_id=job.id,
                        document_id=job.document_id,
                        error=str(exc),
                    )
            return await self._jobs.get_job(job.id)
        completed = await self._jobs.complete_job(
            job.id,
            claim_id,
            chunk_count=chunk_count,
        )
        if not completed:
            return await self._jobs.get_job(job.id)
        await self._documents.update_status(job.document_id, DocumentStatus.COMPLETED)
        await self._documents.update_chunk_count(job.document_id, chunk_count)
        await self._append_job_log(
            JobLog(
                document_id=job.document_id,
                correlation_id=job.correlation_id,
                stage="ingest",
                status=DocumentStatus.COMPLETED.value,
                created_at=datetime.now(UTC),
            )
        )
        return await self._jobs.get_job(job.id)

    async def delete(self, document_id: str) -> None:
        await self._documents.delete(document_id)
        await self._engine.vectors.delete_by_document(document_id)

    async def get_document(self, document_id: str) -> Document | None:
        return await self._documents.get_by_id(document_id)

    async def list_documents(self, limit: int = 50, offset: int = 0) -> list[Document]:
        return await self._documents.list_all(limit=limit, offset=offset)

    async def get_job(self, job_id: str) -> IngestJob | None:
        return await self._jobs.get_job(job_id)

    async def _prepare_markdown(self, job: IngestJob) -> tuple[str, str, str]:
        if job.markdown:
            markdown = job.markdown
            source_uri = job.source_uri or f"inline://{job.document_id}"
        else:
            if not job.source_uri:
                raise ValueError("source_uri is required for file-based ingest jobs")
            parsed = await self._parser.parse(
                document_id=job.document_id,
                file_type=job.file_type,
                source_uri=job.source_uri,
            )
            markdown = parsed.markdown
            source_uri = parsed.source_uri
        artifact_uri = job.artifact_uri or await self._artifact_store.write_markdown(
            job.document_id, markdown
        )
        canonical_markdown = await self._artifact_store.read_markdown(artifact_uri)
        return canonical_markdown, source_uri, artifact_uri

    async def _maintain_claim_lease(
        self,
        job_id: str,
        claim_id: str,
        stop_event: asyncio.Event,
    ) -> None:
        if self._claim_heartbeat_interval_seconds <= 0:
            return
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self._claim_heartbeat_interval_seconds,
                )
                return
            except asyncio.TimeoutError:
                renewed = await self._jobs.renew_claim(job_id, claim_id)
                if renewed:
                    continue
                log_event(
                    self._logger,
                    logging.WARNING,
                    "ingest_claim_heartbeat_lost",
                    stage="ingest",
                    job_id=job_id,
                    claim_id=claim_id,
                )
                return

    async def _append_job_log(self, entry: JobLog) -> None:
        try:
            await self._documents.append_job_log(entry)
        except Exception as exc:  # noqa: BLE001 - audit path must not block main ingest flow
            log_event(
                self._logger,
                logging.WARNING,
                "job_log_append_failed",
                stage=entry.stage,
                document_id=entry.document_id,
                correlation_id=entry.correlation_id,
                status=entry.status,
                error=str(exc),
            )
