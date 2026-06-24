from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional


class DocumentAccessRepository(ABC):
    @abstractmethod
    async def get_allowed_doc_ids(
        self,
        user_id: str,
        role: str,
        department: str,
        account_type: str = "internal",
    ) -> Optional[list[str]]:
        """Return document ids the user can read from the local ACL projection."""

    @abstractmethod
    async def upsert_access(
        self,
        document_id: str,
        classification: str,
        allowed_departments: list[str],
        allowed_user_ids: list[str],
        occurred_at: datetime | None = None,
    ) -> None:
        """Upsert local ACL projection from doc.access events."""

    @abstractmethod
    async def delete_access(self, document_id: str) -> None:
        """Delete local ACL projection when doc.access deleted=true arrives."""

    @abstractmethod
    async def rename_department(self, old_name: str, new_name: str) -> int:
        """Replace old department name with new one in all allowed_departments arrays. Returns count updated."""
