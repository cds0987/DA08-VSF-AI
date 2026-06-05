from app.application.auth import CurrentUser
from app.application.exceptions import NotFoundError
from app.application.use_cases.documents.common import require_admin
from app.domain.entities.document import Document
from app.domain.repositories.document_repository import DocumentRepository


class GetDocumentUseCase:
    def __init__(self, document_repository: DocumentRepository) -> None:
        self.document_repository = document_repository

    async def execute(self, actor: CurrentUser, document_id: str) -> Document:
        require_admin(actor)
        document = await self.document_repository.get_by_id(document_id)
        if document is None:
            raise NotFoundError()
        return document

