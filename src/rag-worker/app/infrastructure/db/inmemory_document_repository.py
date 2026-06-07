from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from typing import List, Optional

from app.domain.entities.document import Document, DocumentStatus
from app.domain.entities.ingest_job import IngestJob, IngestJobStatus
from app.domain.entities.job_log import JobLog
from app.domain.repositories.document_repository import DocumentRepository
from app.domain.repositories.ingest_job_repository import IngestJobRepository


class InMemoryDocumentRepository(DocumentRepository, IngestJobRepository):
    def __init__(self) -> None:
        self._documents: dict[str, Document] = {}
        self._job_logs: list[JobLog] = []
        self._jobs: dict[str, IngestJob] = {}
        self._max_attempts = max(1, int(os.getenv("INGEST_MAX_ATTEMPTS", "5")))

    async def create(self, document: Document) -> Document:
        existing = self._documents.get(document.id)
        if existing is not None:
            return existing
        self._documents[document.id] = document
        return document

    async def get_by_id(self, document_id: str) -> Optional[Document]:
        return self._documents.get(document_id)

    async def list_all(self, limit: int = 50, offset: int = 0) -> List[Document]:
        documents = list(self._documents.values())
        return documents[offset : offset + limit]

    async def update_status(
        self,
        document_id: str,
        status: DocumentStatus,
        error: Optional[str] = None,
    ) -> None:
        document = self._documents.get(document_id)
        if document is None:
            return
        next_error = document.error_message
        if error is not None:
            next_error = error
        elif status is DocumentStatus.COMPLETED:
            next_error = None
        self._documents[document_id] = replace(
            document,
            status=status,
            error_message=next_error,
        )

    async def update_chunk_count(self, document_id: str, chunk_count: int) -> None:
        document = self._documents.get(document_id)
        if document is None:
            return
        self._documents[document_id] = replace(document, chunk_count=chunk_count)

    async def delete(self, document_id: str) -> None:
        self._documents.pop(document_id, None)
        self._job_logs = [entry for entry in self._job_logs if entry.document_id != document_id]
        self._jobs = {
            job_id: job for job_id, job in self._jobs.items() if job.document_id != document_id
        }

    async def append_job_log(self, entry: JobLog) -> JobLog:
        self._job_logs.append(entry)
        return entry

    async def list_job_logs(
        self,
        document_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[JobLog]:
        logs = sorted(
            self._job_logs,
            key=lambda entry: (entry.created_at, entry.document_id),
            reverse=True,
        )
        if document_id is not None:
            logs = [entry for entry in logs if entry.document_id == document_id]
        return logs[offset : offset + limit]

    async def prune_job_logs_older_than(self, cutoff: datetime) -> int:
        before = len(self._job_logs)
        self._job_logs = [entry for entry in self._job_logs if entry.created_at >= cutoff]
        return before - len(self._job_logs)

    async def enqueue(self, job: IngestJob) -> IngestJob:
        self._jobs[job.id] = job
        return job

    async def get_job(self, job_id: str) -> IngestJob | None:
        return self._jobs.get(job_id)

    async def find_active_job(self, document_id: str) -> IngestJob | None:
        active = {
            IngestJobStatus.PENDING,
            IngestJobStatus.PROCESSING,
            IngestJobStatus.STALE,
        }
        candidates = [
            job
            for job in self._jobs.values()
            if job.document_id == document_id and job.status in active
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: (item.created_at, item.id))[0]

    async def claim_next_pending(self, claim_id: str) -> IngestJob | None:
        candidates = sorted(
            self._jobs.values(),
            key=lambda item: (item.created_at, item.id),
        )
        for job in candidates:
            if job.status not in {IngestJobStatus.PENDING, IngestJobStatus.STALE}:
                continue
            if job.attempt >= self._max_attempts:
                continue
            updated = IngestJob(
                id=job.id,
                document_id=job.document_id,
                document_name=job.document_name,
                file_type=job.file_type,
                source_uri=job.source_uri,
                markdown=job.markdown,
                artifact_uri=job.artifact_uri,
                correlation_id=job.correlation_id,
                status=IngestJobStatus.PROCESSING,
                claim_id=claim_id,
                attempt=job.attempt + 1,
                chunk_count=job.chunk_count,
                error_message=job.error_message,
                created_at=job.created_at,
                updated_at=datetime.now(UTC),
            )
            self._jobs[job.id] = updated
            return updated
        return None

    async def renew_claim(self, job_id: str, claim_id: str) -> bool:
        job = self._jobs.get(job_id)
        if (
            job is None
            or job.claim_id != claim_id
            or job.status is not IngestJobStatus.PROCESSING
        ):
            return False
        self._jobs[job_id] = replace(job, updated_at=datetime.now(UTC))
        return True

    async def mark_stale_jobs(self, stale_before: datetime) -> int:
        failed = await self._fail_jobs_exceeding_max_attempts(
            statuses={IngestJobStatus.PROCESSING, IngestJobStatus.STALE},
            stale_before=stale_before,
        )
        marked = 0
        for job_id, job in list(self._jobs.items()):
            if (
                job.status is IngestJobStatus.PROCESSING
                and job.updated_at < stale_before
                and job.attempt < self._max_attempts
            ):
                self._jobs[job_id] = replace(
                    job,
                    status=IngestJobStatus.STALE,
                    claim_id=None,
                    updated_at=datetime.now(UTC),
                )
                marked += 1
        return failed + marked

    async def complete_job(
        self,
        job_id: str,
        claim_id: str,
        *,
        chunk_count: int,
    ) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.claim_id != claim_id:
            return False
        self._jobs[job_id] = IngestJob(
            id=job.id,
            document_id=job.document_id,
            document_name=job.document_name,
            file_type=job.file_type,
            source_uri=job.source_uri,
            markdown=job.markdown,
            artifact_uri=job.artifact_uri,
            correlation_id=job.correlation_id,
            status=IngestJobStatus.COMPLETED,
            claim_id=claim_id,
            attempt=job.attempt,
            chunk_count=chunk_count,
            error_message=None,
            created_at=job.created_at,
            updated_at=datetime.now(UTC),
        )
        return True

    async def _fail_jobs_exceeding_max_attempts(
        self,
        *,
        statuses: set[IngestJobStatus],
        stale_before: datetime | None = None,
    ) -> int:
        now = datetime.now(UTC)
        failed = 0
        for job_id, job in list(self._jobs.items()):
            if job.status not in statuses or job.attempt < self._max_attempts:
                continue
            if stale_before is not None and job.updated_at >= stale_before:
                continue
            self._jobs[job_id] = replace(
                job,
                status=IngestJobStatus.FAILED,
                claim_id=None,
                updated_at=now,
                error_message="exceeded max attempts",
            )
            document = self._documents.get(job.document_id)
            if document is not None:
                self._documents[job.document_id] = replace(
                    document,
                    status=DocumentStatus.FAILED,
                    error_message="exceeded max attempts",
                )
            self._job_logs.append(
                JobLog(
                    document_id=job.document_id,
                    correlation_id=job.correlation_id,
                    stage="ingest",
                    status=DocumentStatus.FAILED.value,
                    error_type="MaxAttemptsExceeded",
                    error_message="exceeded max attempts",
                    created_at=now,
                )
            )
            failed += 1
        return failed

    async def fail_job(
        self,
        job_id: str,
        claim_id: str,
        *,
        error_message: str,
    ) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.claim_id != claim_id:
            return False
        self._jobs[job_id] = IngestJob(
            id=job.id,
            document_id=job.document_id,
            document_name=job.document_name,
            file_type=job.file_type,
            source_uri=job.source_uri,
            markdown=job.markdown,
            artifact_uri=job.artifact_uri,
            correlation_id=job.correlation_id,
            status=IngestJobStatus.FAILED,
            claim_id=claim_id,
            attempt=job.attempt,
            chunk_count=job.chunk_count,
            error_message=error_message,
            created_at=job.created_at,
            updated_at=datetime.now(UTC),
        )
        return True
