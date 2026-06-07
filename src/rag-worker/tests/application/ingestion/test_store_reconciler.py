from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import pytest

from app.application.use_cases.ingestion.store_reconciler import (
    RAW_PREFIX,
    StoreReconcileSettings,
    parse_object_key,
    reconcile_store_once,
)
from app.domain.entities.document import Document, DocumentStatus
from app.domain.entities.ingest_job import IngestJob, IngestJobStatus
from app.domain.repositories.object_store_lister import StoredObject
from app.infrastructure.db import InMemoryDocumentRepository


class _StubEngine:
    vectors = None


class _StubParser:
    async def parse(self, **kwargs):
        raise NotImplementedError


class _StubArtifactStore:
    async def write_markdown(self, document_id: str, markdown: str) -> str:
        return f"artifact://{document_id}"

    async def read_markdown(self, artifact_uri: str) -> str:
        return ""

    async def delete_by_document(self, document_id: str) -> None:
        return None


class _FakeLister:
    def __init__(self, objects: list[StoredObject]) -> None:
        self._objects = objects

    async def list_objects(self, prefix: str):
        assert prefix == RAW_PREFIX
        for obj in self._objects:
            yield obj


def _use_case(repository: InMemoryDocumentRepository):
    from app.application.use_cases.ingestion import IngestDocumentUseCase

    return IngestDocumentUseCase(
        _StubEngine(),
        repository,
        repository,
        _StubParser(),
        _StubArtifactStore(),
    )


def test_parse_object_key() -> None:
    assert parse_object_key("raw/doc-1/file.pdf") == ("doc-1", "file.pdf", "pdf")
    assert parse_object_key("other/doc-1/file.pdf") is None
    assert parse_object_key("raw/doc-1/") is None
    assert parse_object_key("raw/doc-1/file") is None


@pytest.mark.asyncio
async def test_reconcile_enqueues_only_unknown_old_enough_objects() -> None:
    repository = InMemoryDocumentRepository()
    await repository.create(
        Document(
            id="done",
            name="Done",
            file_type="pdf",
            s3_key="s3://bucket/raw/done/file.pdf",
            status=DocumentStatus.COMPLETED,
            created_at=datetime.now(UTC),
        )
    )
    await repository.create(
        Document(
            id="deleted",
            name="Deleted",
            file_type="pdf",
            s3_key="s3://bucket/raw/deleted/file.pdf",
            status=DocumentStatus.DELETED,
            created_at=datetime.now(UTC),
        )
    )
    use_case = _use_case(repository)
    now = datetime.now(UTC)
    lister = _FakeLister(
        [
            StoredObject("raw/new/file.pdf", 10, now - timedelta(hours=1)),
            StoredObject("raw/done/file.pdf", 10, now - timedelta(hours=1)),
            StoredObject("raw/deleted/file.pdf", 10, now - timedelta(hours=1)),
            StoredObject("raw/fresh/file.pdf", 10, now - timedelta(seconds=30)),
            StoredObject("bad-key", 10, now - timedelta(hours=1)),
        ]
    )

    enqueued = await reconcile_store_once(
        lister,
        use_case,
        StoreReconcileSettings(enabled=True, interval_seconds=900, min_age_seconds=60, bucket="docs"),
        logging.getLogger("test"),
    )

    assert enqueued == 1
    active_job = await repository.find_active_job("new")
    assert active_job is not None
    assert active_job.source_uri == "s3://docs/raw/new/file.pdf"
    assert await repository.find_active_job("done") is None
    assert await repository.find_active_job("deleted") is None


@pytest.mark.asyncio
async def test_reconcile_is_idempotent_across_multiple_sweeps() -> None:
    repository = InMemoryDocumentRepository()
    use_case = _use_case(repository)
    now = datetime.now(UTC) - timedelta(hours=1)
    lister = _FakeLister([StoredObject("raw/new/file.pdf", 10, now)])
    settings = StoreReconcileSettings(
        enabled=True,
        interval_seconds=900,
        min_age_seconds=60,
        bucket="docs",
    )

    first = await reconcile_store_once(lister, use_case, settings, logging.getLogger("test"))
    second = await reconcile_store_once(lister, use_case, settings, logging.getLogger("test"))

    assert first == 1
    assert second == 0


@pytest.mark.asyncio
async def test_reconcile_reenqueues_old_transient_failed_document() -> None:
    repository = InMemoryDocumentRepository()
    now = datetime.now(UTC)
    await repository.create(
        Document(
            id="failed-doc",
            name="Failed",
            file_type="pdf",
            s3_key="s3://bucket/raw/failed-doc/file.pdf",
            status=DocumentStatus.FAILED,
            created_at=now,
        )
    )
    await repository.enqueue(
        IngestJob(
            id="job-failed-1",
            document_id="failed-doc",
            document_name="Failed",
            file_type="pdf",
            source_uri="s3://bucket/raw/failed-doc/file.pdf",
            markdown=None,
            artifact_uri=None,
            correlation_id="cid-failed-1",
            status=IngestJobStatus.FAILED,
            created_at=now - timedelta(hours=2),
            updated_at=now - timedelta(hours=2),
            error_message="provider down",
            error_class="transient",
            reconcile_attempt=1,
        )
    )
    use_case = _use_case(repository)
    lister = _FakeLister([StoredObject("raw/failed-doc/file.pdf", 10, now - timedelta(hours=1))])

    enqueued = await reconcile_store_once(
        lister,
        use_case,
        StoreReconcileSettings(
            enabled=True,
            interval_seconds=900,
            min_age_seconds=60,
            bucket="docs",
            max_failed_reconcile_attempts=3,
        ),
        logging.getLogger("test"),
    )

    assert enqueued == 1
    active = await repository.find_active_job("failed-doc")
    assert active is not None
    assert active.status is IngestJobStatus.PENDING
    assert active.reconcile_attempt == 2


@pytest.mark.asyncio
async def test_reconcile_skips_permanent_or_capped_failed_document() -> None:
    repository = InMemoryDocumentRepository()
    now = datetime.now(UTC)
    for doc_id in ("permanent-doc", "capped-doc"):
        await repository.create(
            Document(
                id=doc_id,
                name=doc_id,
                file_type="pdf",
                s3_key=f"s3://bucket/raw/{doc_id}/file.pdf",
                status=DocumentStatus.FAILED,
                created_at=now,
            )
        )
    await repository.enqueue(
        IngestJob(
            id="job-permanent",
            document_id="permanent-doc",
            document_name="Permanent",
            file_type="pdf",
            source_uri="s3://bucket/raw/permanent-doc/file.pdf",
            markdown=None,
            artifact_uri=None,
            correlation_id="cid-permanent",
            status=IngestJobStatus.FAILED,
            created_at=now - timedelta(hours=2),
            updated_at=now - timedelta(hours=2),
            error_message="bad request",
            error_class="permanent",
        )
    )
    await repository.enqueue(
        IngestJob(
            id="job-capped",
            document_id="capped-doc",
            document_name="Capped",
            file_type="pdf",
            source_uri="s3://bucket/raw/capped-doc/file.pdf",
            markdown=None,
            artifact_uri=None,
            correlation_id="cid-capped",
            status=IngestJobStatus.FAILED,
            created_at=now - timedelta(hours=2),
            updated_at=now - timedelta(hours=2),
            error_message="provider down",
            error_class="transient",
            reconcile_attempt=3,
        )
    )
    use_case = _use_case(repository)
    lister = _FakeLister(
        [
            StoredObject("raw/permanent-doc/file.pdf", 10, now - timedelta(hours=1)),
            StoredObject("raw/capped-doc/file.pdf", 10, now - timedelta(hours=1)),
        ]
    )

    enqueued = await reconcile_store_once(
        lister,
        use_case,
        StoreReconcileSettings(
            enabled=True,
            interval_seconds=900,
            min_age_seconds=60,
            bucket="docs",
            max_failed_reconcile_attempts=3,
        ),
        logging.getLogger("test"),
    )

    assert enqueued == 0
    assert await repository.find_active_job("permanent-doc") is None
    assert await repository.find_active_job("capped-doc") is None
