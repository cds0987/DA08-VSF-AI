from __future__ import annotations

import logging
from datetime import datetime, UTC

from app.domain.entities.document import Document, DocumentStatus
from app.domain.entities.job_log import JobLog
from app.domain.repositories.document_repository import DocumentRepository
from haystack_interface.engine import HaystackRagEngine, IngestInput
from haystack_interface.logging_utils import log_event


class IngestDocumentUseCase:
    def __init__(self, engine: HaystackRagEngine, document_repository: DocumentRepository):
        self._engine = engine
        self._documents = document_repository
        self._logger = logging.getLogger(__name__)

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
        request_correlation_id = correlation_id or f"ingest:{document_id}"
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
        await self._append_job_log(
            JobLog(
                document_id=document_id,
                correlation_id=request_correlation_id,
                stage="ingest",
                status=DocumentStatus.PROCESSING.value,
                created_at=datetime.now(UTC),
            )
        )
        try:
            chunk_count = await self._engine.ingest(
                IngestInput(
                    document_id=document_id,
                    document_name=document_name,
                    file_type=file_type,
                    markdown=markdown,
                    source_uri=source_uri,
                    artifact_uri=artifact_uri,
                    correlation_id=request_correlation_id,
                )
            )
        except Exception as exc:
            await self._documents.update_status(
                document_id,
                DocumentStatus.FAILED,
                error=str(exc),
            )
            await self._append_job_log(
                JobLog(
                    document_id=document_id,
                    correlation_id=request_correlation_id,
                    stage="ingest",
                    status=DocumentStatus.FAILED.value,
                    error_type=exc.__class__.__name__,
                    error_message=str(exc),
                    created_at=datetime.now(UTC),
                )
            )
            raise
        await self._documents.update_status(document_id, DocumentStatus.COMPLETED)
        await self._documents.update_chunk_count(document_id, chunk_count)
        await self._append_job_log(
            JobLog(
                document_id=document_id,
                correlation_id=request_correlation_id,
                stage="ingest",
                status=DocumentStatus.COMPLETED.value,
                created_at=datetime.now(UTC),
            )
        )
        return chunk_count

    async def delete(self, document_id: str) -> None:
        await self._engine.vectors.delete_by_document(document_id)
        await self._documents.delete(document_id)

    async def get_document(self, document_id: str) -> Document | None:
        return await self._documents.get_by_id(document_id)

    async def list_documents(self, limit: int = 50, offset: int = 0) -> list[Document]:
        return await self._documents.list_all(limit=limit, offset=offset)

    async def _append_job_log(self, entry: JobLog) -> None:
        try:
            await self._documents.append_job_log(entry)
        except Exception as exc:  # noqa: BLE001 - audit path must not block main ingest flow
            log_event(
                self._logger,
                logging.WARNING,
                "job_log_append_failed",
                stage=entry.stage,
                document_id=entry.document_id,
                correlation_id=entry.correlation_id,
                status=entry.status,
                error=str(exc),
            )
