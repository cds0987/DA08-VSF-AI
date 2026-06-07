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
