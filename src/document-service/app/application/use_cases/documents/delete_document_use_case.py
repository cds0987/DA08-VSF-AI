from dataclasses import dataclass
from typing import Protocol

from app.application.auth import CurrentUser
from app.application.exceptions import NotFoundError
from app.application.use_cases.documents.common import require_admin
from app.domain.repositories.document_repository import DocumentRepository


class DeleteStorage(Protocol):
    async def delete_file(self, key: str) -> None:
        ...


class DeleteEventPublisher(Protocol):
    async def publish_doc_access(self, payload: dict) -> None:
        ...


class AuditLogger(Protocol):
    async def log(
        self,
        action: str,
        actor_id: str,
        actor_role: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        detail: dict | None = None,
        ip_address: str | None = None,
    ) -> None:
        ...


@dataclass(frozen=True)
class DeleteDocumentResult:
    message: str


class DeleteDocumentUseCase:
    def __init__(
        self,
        document_repository: DocumentRepository,
        storage: DeleteStorage,
        publisher: DeleteEventPublisher,
        audit_logger: AuditLogger,
    ) -> None:
        self.document_repository = document_repository
        self.storage = storage
        self.publisher = publisher
        self.audit_logger = audit_logger

    async def execute(
        self,
        actor: CurrentUser,
        document_id: str,
        ip_address: str | None = None,
    ) -> DeleteDocumentResult:
        require_admin(actor)
        document = await self.document_repository.get_by_id(document_id)
        if document is None:
            raise NotFoundError()

        await self.storage.delete_file(document.gcs_key)
        await self.document_repository.delete(document.id)
        await self.publisher.publish_doc_access(
            {
                "doc_id": document.id,
                "classification": document.classification,
                "allowed_departments": document.allowed_departments,
                "allowed_user_ids": document.allowed_user_ids,
                "deleted": True,
            },
        )
        # TODO: publish vector-delete event once infra/nats/subjects.md defines a subject/payload.
        await self.audit_logger.log(
            action="delete",
            actor_id=actor.id,
            actor_role=actor.role,
            resource_type="document",
            resource_id=document.id,
            detail={"gcs_key": document.gcs_key},
            ip_address=ip_address,
        )
        return DeleteDocumentResult(message="Document deleted")

