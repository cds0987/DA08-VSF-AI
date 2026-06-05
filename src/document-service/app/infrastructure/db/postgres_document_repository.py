from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.document import Document, DocumentStatus
from app.domain.repositories.document_repository import DocumentRepository
from app.infrastructure.db.models import DocumentModel


class PostgresDocumentRepository(DocumentRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, document: Document) -> Document:
        model = DocumentModel(
            id=_uuid(document.id),
            name=document.name,
            file_type=document.file_type,
            gcs_key=document.gcs_key,
            status=_status_value(document.status),
            uploaded_by=_uuid(document.uploaded_by),
            classification=document.classification,
            allowed_departments=document.allowed_departments,
            allowed_user_ids=document.allowed_user_ids,
            chunk_count=document.chunk_count,
            error_message=document.error_message,
            created_at=document.created_at,
        )
        self.session.add(model)
        await self.session.commit()
        await self.session.refresh(model)
        return _to_entity(model)

    async def get_by_id(self, document_id: str) -> Document | None:
        result = await self.session.execute(
            select(DocumentModel).where(
                DocumentModel.id == _uuid(document_id),
                DocumentModel.deleted_at.is_(None),
            ),
        )
        model = result.scalar_one_or_none()
        return _to_entity(model) if model else None

    async def list_all(
        self,
        status: DocumentStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Document], int]:
        filters = [DocumentModel.deleted_at.is_(None)]
        if status is not None:
            filters.append(DocumentModel.status == _status_value(status))

        total_result = await self.session.execute(
            select(func.count()).select_from(DocumentModel).where(*filters),
        )
        result = await self.session.execute(
            select(DocumentModel)
            .where(*filters)
            .order_by(DocumentModel.created_at.desc())
            .limit(limit)
            .offset(offset),
        )
        return [_to_entity(model) for model in result.scalars().all()], int(total_result.scalar_one())

    async def update_status(
        self,
        document_id: str,
        status: DocumentStatus,
        chunk_count: int = 0,
        error: str | None = None,
    ) -> None:
        result = await self.session.execute(
            select(DocumentModel).where(
                DocumentModel.id == _uuid(document_id),
                DocumentModel.deleted_at.is_(None),
            ),
        )
        model = result.scalar_one_or_none()
        if model is None:
            return
        model.status = _status_value(status)
        model.chunk_count = chunk_count
        model.error_message = error
        await self.session.commit()

    async def delete(self, document_id: str) -> None:
        result = await self.session.execute(
            select(DocumentModel).where(
                DocumentModel.id == _uuid(document_id),
                DocumentModel.deleted_at.is_(None),
            ),
        )
        model = result.scalar_one_or_none()
        if model is None:
            return
        model.deleted_at = func.now()
        await self.session.commit()


def _to_entity(model: DocumentModel) -> Document:
    return Document(
        id=str(model.id),
        name=model.name,
        file_type=model.file_type,
        gcs_key=model.gcs_key,
        status=DocumentStatus(model.status),
        uploaded_by=str(model.uploaded_by),
        created_at=model.created_at,
        chunk_count=model.chunk_count,
        error_message=model.error_message,
        classification=model.classification,
        allowed_departments=list(model.allowed_departments or []),
        allowed_user_ids=list(model.allowed_user_ids or []),
    )


def _uuid(value: str) -> UUID:
    return UUID(str(value))


def _status_value(status: object) -> str:
    value = getattr(status, "value", None)
    return str(value if value is not None else status)

