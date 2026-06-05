from dataclasses import dataclass
from typing import Protocol

from app.application.auth import CurrentUser
from app.application.exceptions import NotFoundError, PermissionDeniedError
from app.application.use_cases.documents.common import can_access_document
from app.domain.repositories.document_repository import DocumentRepository


class PresignedStorage(Protocol):
    async def generate_presigned_url(self, key: str, expires_in: int = 300) -> str:
        ...


@dataclass(frozen=True)
class DocumentFileResult:
    url: str
    file_type: str
    expires_in: int = 300


class GetDocumentFileUseCase:
    def __init__(
        self,
        document_repository: DocumentRepository,
        storage: PresignedStorage,
    ) -> None:
        self.document_repository = document_repository
        self.storage = storage

    async def execute(self, user: CurrentUser, document_id: str) -> DocumentFileResult:
        document = await self.document_repository.get_by_id(document_id)
        if document is None:
            raise NotFoundError()
        if not can_access_document(
            user,
            document.classification,
            document.allowed_departments,
            document.allowed_user_ids,
        ):
            raise PermissionDeniedError("Khong co quyen xem tai lieu nay")

        return DocumentFileResult(
            url=await self.storage.generate_presigned_url(document.gcs_key, expires_in=300),
            file_type=document.file_type,
            expires_in=300,
        )

