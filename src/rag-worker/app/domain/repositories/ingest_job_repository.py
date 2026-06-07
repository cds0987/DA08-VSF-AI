from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.domain.entities.ingest_job import IngestJob


class IngestJobRepository(ABC):
    @abstractmethod
    async def enqueue(self, job: IngestJob) -> IngestJob:
        """Persist a new pending ingest job."""

    @abstractmethod
    async def get_job(self, job_id: str) -> IngestJob | None:
        """Return a job by id."""

    @abstractmethod
    async def find_active_job(self, document_id: str) -> IngestJob | None:
        """Return a non-terminal (pending/processing/stale) job for the document, if any.

        Dùng để dedup redelivery NATS: bỏ qua enqueue nếu đã có job đang chờ/chạy
        cho cùng document_id. (Khử trùng tuyệt đối cần unique partial index ở DB —
        TODO; check này phủ trường hợp redelivery phổ biến vì redeliver tới SAU.)
        """

    @abstractmethod
    async def claim_next_pending(self, claim_id: str) -> IngestJob | None:
        """Atomically claim one pending/stale job for processing."""

    @abstractmethod
    async def renew_claim(self, job_id: str, claim_id: str) -> bool:
        """Refresh the lease timestamp for an in-flight claimed job."""

    @abstractmethod
    async def mark_stale_jobs(self, stale_before: datetime) -> int:
        """Requeue timed-out processing jobs by marking them stale."""

    @abstractmethod
    async def complete_job(
        self,
        job_id: str,
        claim_id: str,
        *,
        chunk_count: int,
    ) -> bool:
        """Mark a claimed job completed. Return False if claim no longer owns the job."""

    @abstractmethod
    async def fail_job(
        self,
        job_id: str,
        claim_id: str,
        *,
        error_message: str,
    ) -> bool:
        """Mark a claimed job failed. Return False if claim no longer owns the job."""

    @abstractmethod
    async def list_pending_status_publications(
        self,
        limit: int,
        *,
        older_than: datetime | None = None,
    ) -> list[IngestJob]:
        """Return terminal jobs whose doc.status has not been published yet."""

    @abstractmethod
    async def mark_status_published(self, job_id: str) -> None:
        """Mark a terminal job's doc.status as successfully published."""
