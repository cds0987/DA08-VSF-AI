from abc import ABC, abstractmethod
from typing import Optional

from app.domain.entities.document import Document, DocumentStatus


class DocumentRepository(ABC):
    @abstractmethod
    async def create(self, document: Document) -> Document:
        raise NotImplementedError

    @abstractmethod
    async def get_by_id(self, document_id: str) -> Optional[Document]:
        raise NotImplementedError

    @abstractmethod
    async def list_all(
        self,
        status: Optional[DocumentStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Document], int]:
        raise NotImplementedError

    @abstractmethod
    async def update_status(
        self,
        document_id: str,
        status: DocumentStatus,
        chunk_count: int = 0,
        error: Optional[str] = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, document_id: str) -> None:
        raise NotImplementedError

