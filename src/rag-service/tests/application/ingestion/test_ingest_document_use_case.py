import pytest

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
    use_case = IngestDocumentUseCase(engine)

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


@pytest.mark.asyncio
async def test_ingest_use_case_deletes_document_vectors() -> None:
    engine = StubEngine()
    use_case = IngestDocumentUseCase(engine)

    await use_case.delete("doc-2")

    assert engine.vectors.deleted == ["doc-2"]
