from __future__ import annotations

from dataclasses import replace
from typing import List, Optional

from app.domain.entities.document import Document, DocumentStatus
from app.domain.repositories.document_repository import DocumentRepository


class InMemoryDocumentRepository(DocumentRepository):
    def __init__(self) -> None:
        self._documents: dict[str, Document] = {}

    async def create(self, document: Document) -> Document:
        self._documents[document.id] = document
        return document

    async def get_by_id(self, document_id: str) -> Optional[Document]:
        return self._documents.get(document_id)

    async def list_all(self, limit: int = 50, offset: int = 0) -> List[Document]:
        documents = list(self._documents.values())
        return documents[offset : offset + limit]

    async def update_status(
        self,
        document_id: str,
        status: DocumentStatus,
        error: Optional[str] = None,
    ) -> None:
        document = self._documents.get(document_id)
        if document is None:
            return
        self._documents[document_id] = replace(
            document,
            status=status,
            error_message=error,
        )

    async def update_chunk_count(self, document_id: str, chunk_count: int) -> None:
        document = self._documents.get(document_id)
        if document is None:
            return
        self._documents[document_id] = replace(document, chunk_count=chunk_count)

    async def delete(self, document_id: str) -> None:
        self._documents.pop(document_id, None)
