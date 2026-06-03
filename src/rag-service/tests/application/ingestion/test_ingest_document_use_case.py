import pytest

from app.infrastructure.db import InMemoryDocumentRepository
from app.application.use_cases.ingestion import IngestDocumentUseCase


class StubVectors:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete_by_document(self, document_id: str) -> None:
        self.deleted.append(document_id)


class StubEngine:
    def __init__(self) -> None:
        self.ingest_calls = []
        self.vectors = StubVectors()

    async def ingest(self, payload):
        self.ingest_calls.append(payload)
        return 3


@pytest.mark.asyncio
async def test_ingest_use_case_maps_request_into_engine_input() -> None:
    engine = StubEngine()
    documents = InMemoryDocumentRepository()
    use_case = IngestDocumentUseCase(engine, documents)

    chunk_count = await use_case.ingest(
        document_id="doc-1",
        document_name="Guide",
        file_type="md",
        markdown="# Title\nBody",
        source_uri="s3://bucket/doc-1.md",
        artifact_uri="s3://bucket/doc-1.artifact.md",
    )

    assert chunk_count == 3
    ingest_input = engine.ingest_calls[0]
    assert ingest_input.document_id == "doc-1"
    assert ingest_input.document_name == "Guide"
    assert ingest_input.source_uri == "s3://bucket/doc-1.md"
    stored = await use_case.get_document("doc-1")
    assert stored is not None
    assert stored.status.value == "completed"
    assert stored.chunk_count == 3
    logs = await documents.list_job_logs("doc-1")
    assert [entry.status for entry in logs] == ["processing", "completed"]
    assert all(entry.correlation_id == "ingest:doc-1" for entry in logs)


@pytest.mark.asyncio
async def test_ingest_use_case_deletes_document_vectors() -> None:
    engine = StubEngine()
    documents = InMemoryDocumentRepository()
    use_case = IngestDocumentUseCase(engine, documents)

    await use_case.ingest(
        document_id="doc-2",
        document_name="Guide",
        file_type="md",
        markdown="# Title\nBody",
    )

    await use_case.delete("doc-2")

    assert engine.vectors.deleted == ["doc-2"]
    assert await use_case.get_document("doc-2") is None


class FailingEngine(StubEngine):
    async def ingest(self, payload):
        raise RuntimeError("embed failed")


@pytest.mark.asyncio
async def test_ingest_use_case_logs_failed_runs() -> None:
    engine = FailingEngine()
    documents = InMemoryDocumentRepository()
    use_case = IngestDocumentUseCase(engine, documents)

    with pytest.raises(RuntimeError, match="embed failed"):
        await use_case.ingest(
            document_id="doc-fail",
            document_name="Guide",
            file_type="md",
            markdown="# Title\nBody",
        )

    stored = await use_case.get_document("doc-fail")
    assert stored is not None
    assert stored.status.value == "failed"
    logs = await documents.list_job_logs("doc-fail")
    assert [entry.status for entry in logs] == ["processing", "failed"]
    assert logs[-1].error_type == "RuntimeError"
