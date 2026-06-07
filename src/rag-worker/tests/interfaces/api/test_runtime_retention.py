from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from app.domain.entities.ingest_job import IngestJob, IngestJobStatus
from app.domain.entities.job_log import JobLog
from app.infrastructure.db import InMemoryDocumentRepository
from app.interfaces.api.runtime import (
    DocStatusSweepSettings,
    IngestLeaseSettings,
    JobLogRetentionSettings,
    mark_stale_jobs_once,
    prune_job_logs_once,
    run_doc_status_publisher_sweep,
    run_ingest_worker,
)


def test_prune_job_logs_once_removes_entries_older_than_retention() -> None:
    async def scenario() -> None:
        repository = InMemoryDocumentRepository()
        await repository.append_job_log(
            JobLog(
                document_id="doc-1",
                correlation_id="old",
                stage="ingest",
                status="failed",
                created_at=datetime(2024, 1, 1, tzinfo=UTC),
            )
        )
        await repository.append_job_log(
            JobLog(
                document_id="doc-1",
                correlation_id="new",
                stage="ingest",
                status="completed",
                created_at=datetime.now(UTC),
            )
        )

        pruned = await prune_job_logs_once(
            repository,
            JobLogRetentionSettings(retention_days=30, prune_interval_seconds=60),
            logging.getLogger("test"),
        )

        assert pruned == 1
        remaining = await repository.list_job_logs("doc-1")
        assert [entry.correlation_id for entry in remaining] == ["new"]

    asyncio.run(scenario())


def test_mark_stale_jobs_once_requeues_timed_out_processing_jobs() -> None:
    async def scenario() -> None:
        repository = InMemoryDocumentRepository()
        await repository.enqueue(
            IngestJob(
                id="job-1",
                document_id="doc-1",
                document_name="Guide",
                file_type="pdf",
                source_uri="local://doc-1.pdf",
                markdown=None,
                artifact_uri=None,
                correlation_id="cid-1",
                status=IngestJobStatus.PROCESSING,
                claim_id="claim-old",
                attempt=1,
                created_at=datetime(2024, 1, 1, tzinfo=UTC),
                updated_at=datetime(2024, 1, 1, tzinfo=UTC),
            )
        )

        marked = await mark_stale_jobs_once(
            repository,
            IngestLeaseSettings(
                stale_timeout_seconds=60,
                heartbeat_interval_seconds=10,
                reaper_interval_seconds=10,
            ),
            logging.getLogger("test"),
        )

        assert marked == 1
        job = await repository.get_job("job-1")
        assert job is not None
        assert job.status is IngestJobStatus.STALE
        assert job.claim_id is None

    asyncio.run(scenario())


def test_doc_status_sweep_publishes_unpublished_terminal_jobs() -> None:
    class FakePublisher:
        def __init__(self) -> None:
            self.published: list[str] = []

        async def publish_for_job(self, job: IngestJob) -> bool:
            self.published.append(job.id)
            return True

    async def _cancel_sleep(delay: float) -> None:
        raise asyncio.CancelledError()

    async def scenario() -> None:
        repository = InMemoryDocumentRepository()
        old = datetime.now(UTC)
        await repository.enqueue(
            IngestJob(
                id="job-1",
                document_id="doc-1",
                document_name="Guide",
                file_type="pdf",
                source_uri="local://doc-1.pdf",
                markdown=None,
                artifact_uri=None,
                correlation_id="cid-1",
                status=IngestJobStatus.FAILED,
                claim_id=None,
                attempt=1,
                error_message="boom",
                created_at=old,
                updated_at=old,
            )
        )
        publisher = FakePublisher()
        original_sleep = asyncio.sleep
        asyncio.sleep = _cancel_sleep  # type: ignore[assignment]
        try:
            try:
                await run_doc_status_publisher_sweep(
                    repository,
                    publisher,
                    DocStatusSweepSettings(
                        interval_seconds=30,
                        batch=10,
                        lookback_seconds=86400,
                    ),
                    logging.getLogger("test"),
                )
            except asyncio.CancelledError:
                pass
        finally:
            asyncio.sleep = original_sleep  # type: ignore[assignment]

        assert publisher.published == ["job-1"]
        stored = await repository.get_job("job-1")
        assert stored is not None
        assert stored.status_published_at is not None

    asyncio.run(scenario())


def test_run_ingest_worker_marks_status_published_after_inline_success() -> None:
    class FakeUseCase:
        def __init__(self, job: IngestJob) -> None:
            self._job = job
            self._calls = 0

        async def process_next_job(self) -> IngestJob | None:
            self._calls += 1
            if self._calls == 1:
                return self._job
            raise asyncio.CancelledError()

    class FakePublisher:
        def __init__(self) -> None:
            self.jobs: list[str] = []

        async def publish_for_job(self, job: IngestJob) -> bool:
            self.jobs.append(job.id)
            return True

    async def scenario() -> None:
        repository = InMemoryDocumentRepository()
        now = datetime.now(UTC)
        job = IngestJob(
            id="job-1",
            document_id="doc-1",
            document_name="Guide",
            file_type="pdf",
            source_uri="local://doc-1.pdf",
            markdown=None,
            artifact_uri=None,
            correlation_id="cid-1",
            status=IngestJobStatus.COMPLETED,
            claim_id="claim-1",
            attempt=1,
            chunk_count=3,
            created_at=now,
            updated_at=now,
        )
        await repository.enqueue(job)
        publisher = FakePublisher()

        try:
            await run_ingest_worker(
                "worker-1",
                FakeUseCase(job),
                0.01,
                logging.getLogger("test"),
                publisher.publish_for_job,
                repository,
            )
        except asyncio.CancelledError:
            pass

        assert publisher.jobs == ["job-1"]
        stored = await repository.get_job("job-1")
        assert stored is not None
        assert stored.status_published_at is not None

    asyncio.run(scenario())
