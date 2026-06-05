from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePath
from typing import Protocol
from uuid import uuid4

from app.application.auth import CurrentUser
from app.application.exceptions import MessagingPublishError, ValidationError
from app.application.use_cases.documents.common import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_BYTES,
    normalize_acl_values,
    require_admin,
    validate_classification_and_acl,
)
from app.domain.entities.document import Document, DocumentStatus
from app.domain.repositories.document_repository import DocumentRepository


class DocumentStorage(Protocol):
    async def upload_file(self, key: str, content: bytes, content_type: str | None = None) -> None:
        ...


class DocumentEventPublisher(Protocol):
    async def publish_doc_ingest(self, payload: dict) -> None:
        ...

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
class UploadDocumentResult:
    document_id: str
    status: str
    message: str


class UploadDocumentUseCase:
    def __init__(
        self,
        document_repository: DocumentRepository,
        storage: DocumentStorage,
        publisher: DocumentEventPublisher,
        audit_logger: AuditLogger,
    ) -> None:
        self.document_repository = document_repository
        self.storage = storage
        self.publisher = publisher
        self.audit_logger = audit_logger

    async def execute(
        self,
        actor: CurrentUser,
        filename: str,
        content: bytes,
        classification: str,
        allowed_departments: list[str] | str | None = None,
        allowed_user_ids: list[str] | str | None = None,
        content_type: str | None = None,
        ip_address: str | None = None,
    ) -> UploadDocumentResult:
        require_admin(actor)
        if not filename:
            raise ValidationError("Filename is required")
        if len(content) > MAX_FILE_BYTES:
            raise ValidationError("File exceeds 50MB")

        file_type = _file_extension(filename)
        if file_type not in ALLOWED_EXTENSIONS:
            raise ValidationError("File type not supported")

        acl_departments = normalize_acl_values(allowed_departments)
        acl_user_ids = normalize_acl_values(allowed_user_ids)
        classification = classification.strip().lower()
        validate_classification_and_acl(classification, acl_departments, acl_user_ids)

        document_id = str(uuid4())
        safe_name = PurePath(filename).name
        s3_key = f"raw/{document_id}/{safe_name}"

        await self.storage.upload_file(s3_key, content, content_type=content_type)
        document = await self.document_repository.create(
            Document(
                id=document_id,
                name=safe_name,
                file_type=file_type,
                s3_key=s3_key,
                status=DocumentStatus.QUEUED,
                uploaded_by=actor.id,
                created_at=datetime.now(timezone.utc),
                classification=classification,
                allowed_departments=acl_departments,
                allowed_user_ids=acl_user_ids,
            ),
        )

        try:
            await self.publisher.publish_doc_ingest(
                {
                    "doc_id": document.id,
                    "s3_key": document.s3_key,
                    "file_type": document.file_type,
                    "classification": document.classification,
                    "allowed_departments": document.allowed_departments,
                    "allowed_user_ids": document.allowed_user_ids,
                },
            )
            await self.publisher.publish_doc_access(
                {
                    "doc_id": document.id,
                    "classification": document.classification,
                    "allowed_departments": document.allowed_departments,
                    "allowed_user_ids": document.allowed_user_ids,
                    "deleted": False,
                },
            )
        except Exception as exc:
            await self.document_repository.update_status(
                document.id,
                DocumentStatus.FAILED,
                error="event publish failed after upload",
            )
            raise MessagingPublishError("Document queued but event publish failed") from exc

        await self.audit_logger.log(
            action="upload",
            actor_id=actor.id,
            actor_role=actor.role,
            resource_type="document",
            resource_id=document.id,
            detail={
                "name": document.name,
                "file_type": document.file_type,
                "classification": document.classification,
            },
            ip_address=ip_address,
        )
        return UploadDocumentResult(
            document_id=document.id,
            status=DocumentStatus.QUEUED.value,
            message="Ingestion started",
        )


def _file_extension(filename: str) -> str:
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower()

