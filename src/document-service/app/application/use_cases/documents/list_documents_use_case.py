from dataclasses import dataclass

from app.application.auth import CurrentUser
from app.application.use_cases.documents.common import require_admin
from app.domain.entities.document import Document, DocumentStatus
from app.domain.repositories.document_repository import DocumentRepository


@dataclass(frozen=True)
class DocumentListResult:
    items: list[Document]
    total: int


class ListDocumentsUseCase:
    def __init__(self, document_repository: DocumentRepository) -> None:
        self.document_repository = document_repository

    async def execute(
        self,
        actor: CurrentUser,
        status: DocumentStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> DocumentListResult:
        require_admin(actor)
        documents, total = await self.document_repository.list_all(
            status=status,
            limit=limit,
            offset=offset,
        )
        return DocumentListResult(items=documents, total=total)

