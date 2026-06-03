from abc import ABC, abstractmethod
from typing import List, Optional
from app.domain.entities.document import Document, DocumentStatus


class DocumentRepository(ABC):

    @abstractmethod
    async def create(self, document: Document) -> Document:
        """Tạo document record mới."""

    @abstractmethod
    async def get_by_id(self, document_id: str) -> Optional[Document]:
        """Lấy document theo ID."""

    @abstractmethod
    async def list_all(self, limit: int = 50, offset: int = 0) -> List[Document]:
        """Liệt kê tất cả documents."""

    @abstractmethod
    async def update_status(self, document_id: str, status: DocumentStatus, error: Optional[str] = None) -> None:
        """Cập nhật trạng thái ingestion."""

    @abstractmethod
    async def update_chunk_count(self, document_id: str, chunk_count: int) -> None:
        """Cập nhật số chunk đã index của document (sau khi ingest xong)."""

    @abstractmethod
    async def delete(self, document_id: str) -> None:
        """Soft delete document."""
