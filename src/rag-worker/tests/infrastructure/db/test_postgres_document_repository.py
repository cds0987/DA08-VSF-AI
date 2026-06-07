from datetime import UTC, datetime

import pytest

pytest.importorskip("sqlalchemy")

from app.domain.entities.document import Document, DocumentStatus
from app.domain.entities.ingest_job import IngestJob, IngestJobStatus
from app.domain.entities.job_log import JobLog
from app.infrastructure.db import PostgresDocumentRepository


@pytest.mark.asyncio
async def test_postgres_document_repository_crud_roundtrip(tmp_path) -> None:
    database_path = tmp_path / "documents.db"
    repository = PostgresDocumentRepository(f"sqlite:///{database_path}")
    repository.create_schema()

    created = await repository.create(
        Document(
            id="doc-1",
            name="Policy",
            file_type="md",
            s3_key="local://doc-1",
            status=DocumentStatus.PROCESSING,
            created_at=datetime.now(UTC),
        )
    )

    assert created.id == "doc-1"

    stored = await repository.get_by_id("doc-1")
    assert stored is not None
    assert stored.status == DocumentStatus.PROCESSING

    await repository.update_status("doc-1", DocumentStatus.COMPLETED)
    await repository.update_chunk_count("doc-1", 4)
    await repository.append_job_log(
        JobLog(
            document_id="doc-1",
            correlation_id="cid-1",
            stage="ingest",
            status="completed",
            created_at=datetime.now(UTC),
        )
    )

    updated = await repository.get_by_id("doc-1")
    assert updated is not None
    assert updated.status == DocumentStatus.COMPLETED
    assert updated.chunk_count == 4
    logs = await repository.list_job_logs("doc-1")
    assert len(logs) == 1
    assert logs[0].correlation_id == "cid-1"

    documents = await repository.list_all()
    assert [document.id for document in documents] == ["doc-1"]

    await repository.delete("doc-1")
    deleted = await repository.get_by_id("doc-1")
    assert deleted is not None
    assert deleted.status is DocumentStatus.DELETED
    assert await repository.list_all() == []


@pytest.mark.asyncio
async def test_postgres_document_repository_create_duplicate_returns_existing_without_overwrite(tmp_path) -> None:
    database_path = tmp_path / "documents.db"
    repository = PostgresDocumentRepository(f"sqlite:///{database_path}")
    repository.create_schema()
    created_at = datetime.now(UTC)

    first = await repository.create(
        Document(
            id="doc-1",
            name="Original",
            file_type="md",
            s3_key="local://doc-1",
            status=DocumentStatus.COMPLETED,
            created_at=created_at,
            chunk_count=7,
        )
    )
    second = await repository.create(
        Document(
            id="doc-1",
            name="Overwritten",
            file_type="pdf",
            s3_key="local://other",
            status=DocumentStatus.QUEUED,
            created_at=created_at,
            chunk_count=0,
        )
    )

    assert first.name == "Original"
    assert second.name == "Original"
    stored = await repository.get_by_id("doc-1")
    assert stored is not None
    assert stored.status is DocumentStatus.COMPLETED
    assert stored.chunk_count == 7


@pytest.mark.asyncio
async def test_postgres_document_repository_delete_cascades_jobs_and_logs(tmp_path) -> None:
    database_path = tmp_path / "documents.db"
    repository = PostgresDocumentRepository(f"sqlite:///{database_path}")
    repository.create_schema()
    now = datetime.now(UTC)

    await repository.create(
        Document(
            id="doc-1",
            name="Policy",
            file_type="md",
            s3_key="local://doc-1",
            status=DocumentStatus.QUEUED,
            created_at=now,
        )
    )
    await repository.enqueue(
        IngestJob(
            id="job-1",
            document_id="doc-1",
            document_name="Policy",
            file_type="md",
            source_uri="local://doc-1.md",
            markdown="# Policy",
            artifact_uri=None,
            correlation_id="cid-1",
            status=IngestJobStatus.PENDING,
            created_at=now,
            updated_at=now,
        )
    )
    await repository.append_job_log(
        JobLog(
            document_id="doc-1",
            correlation_id="cid-1",
            stage="queue",
            status="pending",
            created_at=now,
        )
    )

    await repository.delete("doc-1")

    deleted = await repository.get_by_id("doc-1")
    assert deleted is not None
    assert deleted.status is DocumentStatus.DELETED
    assert await repository.get_job("job-1") is None
    assert await repository.list_job_logs("doc-1") == []
    assert await repository.list_all() == []


@pytest.mark.asyncio
async def test_postgres_document_repository_claims_and_completes_ingest_jobs(tmp_path) -> None:
    database_path = tmp_path / "documents.db"
    repository = PostgresDocumentRepository(f"sqlite:///{database_path}")
    repository.create_schema()

    created = await repository.enqueue(
        IngestJob(
            id="job-1",
            document_id="doc-1",
            document_name="Policy",
            file_type="md",
            source_uri="local://doc-1.md",
            markdown="# Policy",
            artifact_uri=None,
            correlation_id="cid-1",
            status=IngestJobStatus.PENDING,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )

    assert created.id == "job-1"

    claimed = await repository.claim_next_pending("claim-1")

    assert claimed is not None
    assert claimed.id == "job-1"
    assert claimed.status is IngestJobStatus.PROCESSING
    assert claimed.claim_id == "claim-1"
    assert claimed.attempt == 1
    assert await repository.complete_job("job-1", "claim-1", chunk_count=4) is True
    stored = await repository.get_job("job-1")
    assert stored is not None
    assert stored.status is IngestJobStatus.COMPLETED
    assert stored.chunk_count == 4


@pytest.mark.asyncio
async def test_postgres_document_repository_renews_processing_claim(tmp_path) -> None:
    database_path = tmp_path / "documents.db"
    repository = PostgresDocumentRepository(f"sqlite:///{database_path}")
    repository.create_schema()
    now = datetime.now(UTC)

    await repository.enqueue(
        IngestJob(
            id="job-1",
            document_id="doc-1",
            document_name="Policy",
            file_type="md",
            source_uri="local://doc-1.md",
            markdown="# Policy",
            artifact_uri=None,
            correlation_id="cid-1",
            status=IngestJobStatus.PROCESSING,
            claim_id="claim-1",
            attempt=1,
            created_at=now,
            updated_at=now,
        )
    )

    assert await repository.renew_claim("job-1", "claim-1") is True
    stored = await repository.get_job("job-1")
    assert stored is not None
    assert stored.updated_at >= now


@pytest.mark.asyncio
async def test_postgres_document_repository_terminal_claim_guard_rejects_stale_worker(tmp_path) -> None:
    database_path = tmp_path / "documents.db"
    repository = PostgresDocumentRepository(f"sqlite:///{database_path}")
    repository.create_schema()

    await repository.enqueue(
        IngestJob(
            id="job-1",
            document_id="doc-1",
            document_name="Policy",
            file_type="md",
            source_uri="local://doc-1.md",
            markdown="# Policy",
            artifact_uri=None,
            correlation_id="cid-1",
            status=IngestJobStatus.PROCESSING,
            claim_id="claim-new",
            attempt=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )

    assert await repository.complete_job("job-1", "claim-old", chunk_count=4) is False
    assert await repository.fail_job("job-1", "claim-old", error_message="boom") is False


@pytest.mark.asyncio
async def test_postgres_document_repository_marks_timed_out_jobs_stale(tmp_path) -> None:
    database_path = tmp_path / "documents.db"
    repository = PostgresDocumentRepository(f"sqlite:///{database_path}")
    repository.create_schema()
    old = datetime(2024, 1, 1, tzinfo=UTC)

    await repository.enqueue(
        IngestJob(
            id="job-1",
            document_id="doc-1",
            document_name="Policy",
            file_type="md",
            source_uri="local://doc-1.md",
            markdown="# Policy",
            artifact_uri=None,
            correlation_id="cid-1",
            status=IngestJobStatus.PROCESSING,
            claim_id="claim-old",
            attempt=1,
            created_at=old,
            updated_at=old,
        )
    )

    marked = await repository.mark_stale_jobs(datetime(2025, 1, 1, tzinfo=UTC))

    assert marked == 1
    stored = await repository.get_job("job-1")
    assert stored is not None
    assert stored.status is IngestJobStatus.STALE
    assert stored.claim_id is None


@pytest.mark.asyncio
async def test_postgres_document_repository_fails_stale_jobs_that_hit_max_attempts(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INGEST_MAX_ATTEMPTS", "2")
    database_path = tmp_path / "documents.db"
    repository = PostgresDocumentRepository(f"sqlite:///{database_path}")
    repository.create_schema()
    old = datetime(2024, 1, 1, tzinfo=UTC)

    await repository.create(
        Document(
            id="doc-1",
            name="Policy",
            file_type="md",
            s3_key="local://doc-1",
            status=DocumentStatus.PROCESSING,
            created_at=old,
        )
    )
    await repository.enqueue(
        IngestJob(
            id="job-1",
            document_id="doc-1",
            document_name="Policy",
            file_type="md",
            source_uri="local://doc-1.md",
            markdown="# Policy",
            artifact_uri=None,
            correlation_id="cid-1",
            status=IngestJobStatus.PROCESSING,
            claim_id="claim-old",
            attempt=2,
            created_at=old,
            updated_at=old,
        )
    )

    marked = await repository.mark_stale_jobs(datetime(2025, 1, 1, tzinfo=UTC))

    assert marked == 1
    stored_job = await repository.get_job("job-1")
    assert stored_job is not None
    assert stored_job.status is IngestJobStatus.FAILED
    assert stored_job.error_message == "exceeded max attempts"
    stored_doc = await repository.get_by_id("doc-1")
    assert stored_doc is not None
    assert stored_doc.status is DocumentStatus.FAILED
    assert stored_doc.error_message == "exceeded max attempts"
    logs = await repository.list_job_logs("doc-1")
    assert logs[0].error_type == "MaxAttemptsExceeded"


@pytest.mark.asyncio
async def test_postgres_document_repository_does_not_fail_max_attempt_jobs_during_claim_poll(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INGEST_MAX_ATTEMPTS", "2")
    database_path = tmp_path / "documents.db"
    repository = PostgresDocumentRepository(f"sqlite:///{database_path}")
    repository.create_schema()
    now = datetime.now(UTC)

    await repository.enqueue(
        IngestJob(
            id="job-1",
            document_id="doc-1",
            document_name="Policy",
            file_type="md",
            source_uri="local://doc-1.md",
            markdown="# Policy",
            artifact_uri=None,
            correlation_id="cid-1",
            status=IngestJobStatus.STALE,
            attempt=2,
            created_at=now,
            updated_at=now,
        )
    )

    claimed = await repository.claim_next_pending("claim-1")

    assert claimed is None
    stored = await repository.get_job("job-1")
    assert stored is not None
    assert stored.status is IngestJobStatus.STALE


@pytest.mark.asyncio
async def test_postgres_document_repository_preserves_error_until_completion(tmp_path) -> None:
    database_path = tmp_path / "documents.db"
    repository = PostgresDocumentRepository(f"sqlite:///{database_path}")
    repository.create_schema()
    now = datetime.now(UTC)

    await repository.create(
        Document(
            id="doc-1",
            name="Policy",
            file_type="md",
            s3_key="local://doc-1",
            status=DocumentStatus.FAILED,
            created_at=now,
            error_message="previous failure",
        )
    )

    await repository.update_status("doc-1", DocumentStatus.PROCESSING)
    processing = await repository.get_by_id("doc-1")
    assert processing is not None
    assert processing.error_message == "previous failure"

    await repository.update_status("doc-1", DocumentStatus.COMPLETED)
    completed = await repository.get_by_id("doc-1")
    assert completed is not None
    assert completed.error_message is None


@pytest.mark.asyncio
async def test_postgres_document_repository_does_not_leave_deleted_tombstone(tmp_path) -> None:
    database_path = tmp_path / "documents.db"
    repository = PostgresDocumentRepository(f"sqlite:///{database_path}")
    repository.create_schema()
    now = datetime.now(UTC)

    await repository.create(
        Document(
            id="doc-1",
            name="Policy",
            file_type="md",
            s3_key="local://doc-1",
            status=DocumentStatus.DELETED,
            created_at=now,
        )
    )

    await repository.update_status("doc-1", DocumentStatus.PROCESSING)

    stored = await repository.get_by_id("doc-1")
    assert stored is not None
    assert stored.status is DocumentStatus.DELETED


@pytest.mark.asyncio
async def test_postgres_document_repository_update_missing_document_raises(tmp_path) -> None:
    database_path = tmp_path / "documents.db"
    repository = PostgresDocumentRepository(f"sqlite:///{database_path}")
    repository.create_schema()

    with pytest.raises(KeyError, match="document not found"):
        await repository.update_status("missing", DocumentStatus.FAILED, error="boom")


@pytest.mark.asyncio
async def test_postgres_document_repository_prunes_old_job_logs(tmp_path) -> None:
    database_path = tmp_path / "documents.db"
    repository = PostgresDocumentRepository(f"sqlite:///{database_path}")
    repository.create_schema()

    await repository.append_job_log(
        JobLog(
            document_id="doc-1",
            correlation_id="cid-old",
            stage="ingest",
            status="failed",
            error_type="RuntimeError",
            error_message="boom",
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
    )
    await repository.append_job_log(
        JobLog(
            document_id="doc-1",
            correlation_id="cid-new",
            stage="ingest",
            status="completed",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )

    pruned = await repository.prune_job_logs_older_than(datetime(2025, 1, 1, tzinfo=UTC))

    assert pruned == 1
    logs = await repository.list_job_logs("doc-1")
    assert [entry.correlation_id for entry in logs] == ["cid-new"]
