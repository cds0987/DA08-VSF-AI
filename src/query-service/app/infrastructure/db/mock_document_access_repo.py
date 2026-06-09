from datetime import datetime

from app.domain.repositories.document_access_repository import DocumentAccessRepository
from app.infrastructure.db.mock_data import MOCK_DOCUMENTS, MockDocument


class InMemoryDocumentAccessRepository(DocumentAccessRepository):
    def __init__(self) -> None:
        self._records: dict[str, dict[str, list[str] | str]] = {
            document.id: {
                "classification": document.classification,
                "allowed_departments": list(document.allowed_departments),
                "allowed_user_ids": list(document.allowed_user_ids),
            }
            for document in MOCK_DOCUMENTS
        }

    async def get_allowed_doc_ids(
        self,
        user_id: str,
        role: str,
        department: str,
        account_type: str = "internal",
    ) -> list[str]:
        return [
            document_id
            for document_id, record in self._records.items()
            if can_access_document(
                user_id=user_id,
                role=role,
                department=department,
                account_type=account_type,
                classification=str(record["classification"]),
                allowed_departments=list(record["allowed_departments"]),
                allowed_user_ids=list(record["allowed_user_ids"]),
            )
        ]

    async def upsert_access(
        self,
        document_id: str,
        classification: str,
        allowed_departments: list[str],
        allowed_user_ids: list[str],
        occurred_at: datetime | None = None,
    ) -> None:
        self._records[document_id] = {
            "classification": classification,
            "allowed_departments": list(allowed_departments),
            "allowed_user_ids": list(allowed_user_ids),
        }

    async def delete_access(self, document_id: str) -> None:
        self._records.pop(document_id, None)

    def reset(self) -> None:
        self.__init__()


def can_access_document(
    user_id: str,
    role: str,
    department: str,
    classification: str,
    account_type: str = "internal",
    allowed_departments: list[str] | None = None,
    allowed_user_ids: list[str] | None = None,
) -> bool:
    # Admin bypasses all classification checks regardless of account type.
    if role == "admin":
        return True
    # External accounts (partners/contractors) may only read public documents.
    if account_type == "external":
        return classification == "public"
    # Internal account rules:
    if classification == "public":
        return True
    if classification == "internal":
        return role in {"user", "admin"}
    if classification == "secret":
        return department in (allowed_departments or [])
    if classification == "top_secret":
        return user_id in (allowed_user_ids or [])
    return False


def get_mock_document(document_id: str) -> MockDocument | None:
    for document in MOCK_DOCUMENTS:
        if document.id == document_id:
            return document
    return None
