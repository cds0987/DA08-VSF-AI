from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from app.domain.entities.ingest_job import IngestJob, IngestJobStatus
from app.domain.entities.job_log import JobLog
from app.infrastructure.db import InMemoryDocumentRepository
from app.interfaces.api.runtime import (
    IngestLeaseSettings,
    JobLogRetentionSettings,
    mark_stale_jobs_once,
    prune_job_logs_once,
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
