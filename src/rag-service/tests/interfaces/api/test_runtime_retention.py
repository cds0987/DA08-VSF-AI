from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from app.domain.entities.job_log import JobLog
from app.infrastructure.db import InMemoryDocumentRepository
from app.interfaces.api.runtime import (
    JobLogRetentionSettings,
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
