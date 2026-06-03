from __future__ import annotations

from datetime import datetime, UTC

from app.domain.entities.document import Document, DocumentStatus
from app.domain.repositories.document_repository import DocumentRepository
from haystack_interface.engine import HaystackRagEngine, IngestInput


class IngestDocumentUseCase:
    def __init__(self, engine: HaystackRagEngine, document_repository: DocumentRepository):
        self._engine = engine
        self._documents = document_repository

    async def ingest(
        self,
        *,
        document_id: str,
        document_name: str,
        file_type: str,
        markdown: str,
        source_uri: str | None = None,
        artifact_uri: str | None = None,
        correlation_id: str | None = None,
    ) -> int:
        document = Document(
            id=document_id,
            name=document_name,
            file_type=file_type,
            s3_key=source_uri or f"local://{document_id}",
            status=DocumentStatus.PROCESSING,
            uploaded_by="system",
            created_at=datetime.now(UTC),
        )
        await self._documents.create(document)
        try:
            chunk_count = await self._engine.ingest(
                IngestInput(
                    document_id=document_id,
                    document_name=document_name,
                    file_type=file_type,
                    markdown=markdown,
                    source_uri=source_uri,
                    artifact_uri=artifact_uri,
                    correlation_id=correlation_id,
                )
            )
        except Exception as exc:
            await self._documents.update_status(
                document_id,
                DocumentStatus.FAILED,
                error=str(exc),
            )
            raise
        await self._documents.update_status(document_id, DocumentStatus.COMPLETED)
        if hasattr(self._documents, "update_chunk_count"):
            await self._documents.update_chunk_count(document_id, chunk_count)
        else:
            stored = await self._documents.get_by_id(document_id)
            if stored is not None:
                stored.chunk_count = chunk_count
        return chunk_count

    async def delete(self, document_id: str) -> None:
        await self._engine.vectors.delete_by_document(document_id)
        await self._documents.delete(document_id)

    async def get_document(self, document_id: str) -> Document | None:
        return await self._documents.get_by_id(document_id)

    async def list_documents(self, limit: int = 50, offset: int = 0) -> list[Document]:
        return await self._documents.list_all(limit=limit, offset=offset)
