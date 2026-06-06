from app.application.auth import CurrentUser
from app.application.exceptions import NotFoundError, PermissionDeniedError
from app.application.use_cases.documents.common import can_access_document
from app.domain.entities.document import Document
from app.domain.repositories.document_repository import DocumentRepository


class GetDocumentUseCase:
    def __init__(self, document_repository: DocumentRepository) -> None:
        self.document_repository = document_repository

    async def execute(self, actor: CurrentUser, document_id: str) -> Document:
        document = await self.document_repository.get_by_id(document_id)
        if document is None:
            raise NotFoundError()
        if not can_access_document(
            actor,
            document.classification,
            document.allowed_departments,
            document.allowed_user_ids,
        ):
            raise PermissionDeniedError("Khong co quyen xem tai lieu nay")
        return document

