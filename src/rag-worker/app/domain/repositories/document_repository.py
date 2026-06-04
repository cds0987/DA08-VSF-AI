from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional
from app.domain.entities.document import Document, DocumentStatus
from app.domain.entities.job_log import JobLog


class DocumentRepository(ABC):

    @abstractmethod
    async def create(self, document: Document) -> Document:
        """Create or overwrite document metadata keyed by deterministic document_id."""

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

    @abstractmethod
    async def append_job_log(self, entry: JobLog) -> JobLog:
        """Ghi audit log cho ingestion/search-related document workflow."""

    @abstractmethod
    async def list_job_logs(
        self,
        document_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[JobLog]:
        """Liệt kê job log theo document hoặc toàn cục, mới nhất trước."""

    @abstractmethod
    async def prune_job_logs_older_than(self, cutoff: datetime) -> int:
        """Xoá log cũ hơn mốc retention; trả số dòng đã prune."""
