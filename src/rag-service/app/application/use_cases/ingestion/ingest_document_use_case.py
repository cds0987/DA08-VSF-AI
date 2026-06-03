from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.entities.document import Document, DocumentStatus
from app.domain.entities.ingest_job import IngestJob, IngestJobStatus
from app.domain.entities.job_log import JobLog
from app.domain.repositories.artifact_store import ArtifactStore
from app.domain.repositories.document_repository import DocumentRepository
from app.domain.repositories.ingest_job_repository import IngestJobRepository
from app.domain.repositories.parser import Parser
from haystack_interface.engine import HaystackRagEngine, IngestInput
from haystack_interface.logging_utils import log_event


class IngestDocumentUseCase:
    def __init__(
        self,
        engine: HaystackRagEngine,
        document_repository: DocumentRepository,
        job_repository: IngestJobRepository,
        parser: Parser,
        artifact_store: ArtifactStore,
    ):
        self._engine = engine
        self._documents = document_repository
        self._jobs = job_repository
        self._parser = parser
        self._artifact_store = artifact_store
        self._logger = logging.getLogger(__name__)

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
        await self._jobs.enqueue(job)
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
        try:
            markdown, source_uri, artifact_uri = await self._prepare_markdown(job)
            chunk_count = await self._engine.ingest(
                IngestInput(
                    document_id=job.document_id,
                    document_name=job.document_name,
                    file_type=job.file_type,
                    markdown=markdown,
                    source_uri=source_uri,
                    artifact_uri=artifact_uri,
                    correlation_id=job.correlation_id,
                )
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
            raise
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
        await self._engine.vectors.delete_by_document(document_id)
        await self._documents.delete(document_id)

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
