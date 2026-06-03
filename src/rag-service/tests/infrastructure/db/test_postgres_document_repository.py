from datetime import UTC, datetime

import pytest

pytest.importorskip("sqlalchemy")

from app.domain.entities.document import Document, DocumentStatus
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
            uploaded_by="system",
            created_at=datetime.now(UTC),
        )
    )

    assert created.id == "doc-1"

    stored = await repository.get_by_id("doc-1")
    assert stored is not None
    assert stored.status == DocumentStatus.PROCESSING

    await repository.update_status("doc-1", DocumentStatus.COMPLETED)
    await repository.update_chunk_count("doc-1", 4)

    updated = await repository.get_by_id("doc-1")
    assert updated is not None
    assert updated.status == DocumentStatus.COMPLETED
    assert updated.chunk_count == 4

    documents = await repository.list_all()
    assert [document.id for document in documents] == ["doc-1"]

    await repository.delete("doc-1")
    assert await repository.get_by_id("doc-1") is None


@pytest.mark.asyncio
async def test_postgres_document_repository_update_missing_document_raises(tmp_path) -> None:
    database_path = tmp_path / "documents.db"
    repository = PostgresDocumentRepository(f"sqlite:///{database_path}")
    repository.create_schema()

    with pytest.raises(KeyError, match="document not found"):
        await repository.update_status("missing", DocumentStatus.FAILED, error="boom")
