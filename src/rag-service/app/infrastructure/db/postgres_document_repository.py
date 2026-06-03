from __future__ import annotations

import asyncio
from contextlib import contextmanager

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.domain.entities.document import Document, DocumentStatus
from app.domain.repositories.document_repository import DocumentRepository
from app.infrastructure.db.models import Base, DocumentRecord


class PostgresDocumentRepository(DocumentRepository):
    """SQLAlchemy-backed repository for document metadata.

    Synchronous SQLAlchemy sessions wrapped in `asyncio.to_thread()` (no async
    driver needed). Production points it at PostgreSQL via `DATABASE_URL`.

    Schema KHÔNG tạo ad-hoc ở đây (CONSTRAINTS §3 / DAY0 §2): production phải chạy
    `alembic upgrade head` (migrations/). Dev/test tạo nhanh bằng
    `create_schema()` hoặc `Base.metadata.create_all(repo.engine)`.
    """

    def __init__(self, database_url: str):
        self._engine = create_engine(database_url, future=True)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False)

    @property
    def engine(self) -> Engine:
        return self._engine

    def create_schema(self) -> None:
        """Tạo schema trực tiếp từ models — CHỈ cho dev/test. Production dùng alembic."""
        Base.metadata.create_all(self._engine)

    @contextmanager
    def _session(self) -> Session:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def create(self, document: Document) -> Document:
        return await asyncio.to_thread(self._create_sync, document)

    def _create_sync(self, document: Document) -> Document:
        with self._session() as session:
            record = DocumentRecord(
                id=document.id,
                name=document.name,
                file_type=document.file_type,
                s3_key=document.s3_key,
                status=document.status.value,
                uploaded_by=document.uploaded_by,
                created_at=document.created_at,
                chunk_count=document.chunk_count,
                error_message=document.error_message,
            )
            session.merge(record)
            return self._to_domain(record)

    async def get_by_id(self, document_id: str) -> Document | None:
        return await asyncio.to_thread(self._get_by_id_sync, document_id)

    def _get_by_id_sync(self, document_id: str) -> Document | None:
        with self._session() as session:
            record = session.get(DocumentRecord, document_id)
            if record is None:
                return None
            return self._to_domain(record)

    async def list_all(self, limit: int = 50, offset: int = 0) -> list[Document]:
        return await asyncio.to_thread(self._list_all_sync, limit, offset)

    def _list_all_sync(self, limit: int, offset: int) -> list[Document]:
        with self._session() as session:
            stmt = (
                select(DocumentRecord)
                .order_by(DocumentRecord.created_at.desc(), DocumentRecord.id.desc())
                .offset(offset)
                .limit(limit)
            )
            records = session.execute(stmt).scalars().all()
            return [self._to_domain(record) for record in records]

    async def update_status(
        self,
        document_id: str,
        status: DocumentStatus,
        error: str | None = None,
    ) -> None:
        await asyncio.to_thread(self._update_status_sync, document_id, status, error)

    def _update_status_sync(
        self,
        document_id: str,
        status: DocumentStatus,
        error: str | None,
    ) -> None:
        with self._session() as session:
            record = session.get(DocumentRecord, document_id)
            if record is None:
                raise KeyError(f"document not found: {document_id}")
            record.status = status.value
            record.error_message = error

    async def delete(self, document_id: str) -> None:
        await asyncio.to_thread(self._delete_sync, document_id)

    def _delete_sync(self, document_id: str) -> None:
        with self._session() as session:
            record = session.get(DocumentRecord, document_id)
            if record is not None:
                session.delete(record)

    async def update_chunk_count(self, document_id: str, chunk_count: int) -> None:
        await asyncio.to_thread(self._update_chunk_count_sync, document_id, chunk_count)

    def _update_chunk_count_sync(self, document_id: str, chunk_count: int) -> None:
        with self._session() as session:
            record = session.get(DocumentRecord, document_id)
            if record is None:
                raise KeyError(f"document not found: {document_id}")
            record.chunk_count = chunk_count

    def _to_domain(self, record: DocumentRecord) -> Document:
        return Document(
            id=record.id,
            name=record.name,
            file_type=record.file_type,
            s3_key=record.s3_key,
            status=DocumentStatus(record.status),
            uploaded_by=record.uploaded_by,
            created_at=record.created_at,
            chunk_count=record.chunk_count,
            error_message=record.error_message,
        )
