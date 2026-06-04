from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.domain.entities.document import Document, DocumentStatus
from app.domain.entities.ingest_job import IngestJob, IngestJobStatus
from app.domain.entities.job_log import JobLog
from app.domain.repositories.document_repository import DocumentRepository
from app.domain.repositories.ingest_job_repository import IngestJobRepository
from app.infrastructure.db.models import Base, DocumentRecord, IngestJobRecord, JobLogRecord


class PostgresDocumentRepository(DocumentRepository, IngestJobRepository):
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
            created_at=record.created_at,
            chunk_count=record.chunk_count,
            error_message=record.error_message,
        )

    async def append_job_log(self, entry: JobLog) -> JobLog:
        return await asyncio.to_thread(self._append_job_log_sync, entry)

    def _append_job_log_sync(self, entry: JobLog) -> JobLog:
        with self._session() as session:
            record = JobLogRecord(
                document_id=entry.document_id,
                correlation_id=entry.correlation_id,
                stage=entry.stage,
                status=entry.status,
                error_type=entry.error_type,
                error_message=entry.error_message,
                created_at=entry.created_at,
            )
            session.add(record)
            session.flush()
            return self._to_job_log(record)

    async def list_job_logs(
        self,
        document_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[JobLog]:
        return await asyncio.to_thread(self._list_job_logs_sync, document_id, limit, offset)

    def _list_job_logs_sync(
        self,
        document_id: str | None,
        limit: int,
        offset: int,
    ) -> list[JobLog]:
        with self._session() as session:
            stmt = (
                select(JobLogRecord)
                .order_by(JobLogRecord.created_at.desc(), JobLogRecord.id.desc())
                .offset(offset)
                .limit(limit)
            )
            if document_id is not None:
                stmt = stmt.where(JobLogRecord.document_id == document_id)
            records = session.execute(stmt).scalars().all()
            return [self._to_job_log(record) for record in records]

    async def prune_job_logs_older_than(self, cutoff: datetime) -> int:
        return await asyncio.to_thread(self._prune_job_logs_older_than_sync, cutoff)

    def _prune_job_logs_older_than_sync(self, cutoff: datetime) -> int:
        with self._session() as session:
            result = session.execute(
                delete(JobLogRecord).where(JobLogRecord.created_at < cutoff)
            )
            return int(result.rowcount or 0)

    def _to_job_log(self, record: JobLogRecord) -> JobLog:
        return JobLog(
            document_id=record.document_id,
            correlation_id=record.correlation_id,
            stage=record.stage,
            status=record.status,
            error_type=record.error_type,
            error_message=record.error_message,
            created_at=record.created_at,
        )

    async def enqueue(self, job: IngestJob) -> IngestJob:
        return await asyncio.to_thread(self._enqueue_sync, job)

    def _enqueue_sync(self, job: IngestJob) -> IngestJob:
        with self._session() as session:
            record = IngestJobRecord(
                id=job.id,
                document_id=job.document_id,
                document_name=job.document_name,
                file_type=job.file_type,
                source_uri=job.source_uri,
                markdown=job.markdown,
                artifact_uri=job.artifact_uri,
                correlation_id=job.correlation_id,
                status=job.status.value,
                claim_id=job.claim_id,
                attempt=job.attempt,
                chunk_count=job.chunk_count,
                error_message=job.error_message,
                created_at=job.created_at,
                updated_at=job.updated_at,
            )
            session.merge(record)
            return self._to_job(record)

    async def get_job(self, job_id: str) -> IngestJob | None:
        return await asyncio.to_thread(self._get_job_sync, job_id)

    def _get_job_sync(self, job_id: str) -> IngestJob | None:
        with self._session() as session:
            record = session.get(IngestJobRecord, job_id)
            if record is None:
                return None
            return self._to_job(record)

    async def claim_next_pending(self, claim_id: str) -> IngestJob | None:
        return await asyncio.to_thread(self._claim_next_pending_sync, claim_id)

    def _claim_next_pending_sync(self, claim_id: str) -> IngestJob | None:
        now = datetime.now(UTC)
        with self._session() as session:
            stmt = (
                select(IngestJobRecord)
                .where(
                    IngestJobRecord.status.in_(
                        [IngestJobStatus.PENDING.value, IngestJobStatus.STALE.value]
                    )
                )
                .order_by(IngestJobRecord.created_at.asc(), IngestJobRecord.id.asc())
                .limit(1)
            )
            record = session.execute(stmt).scalars().first()
            if record is None:
                return None
            result = session.execute(
                update(IngestJobRecord)
                .where(
                    IngestJobRecord.id == record.id,
                    IngestJobRecord.status.in_(
                        [IngestJobStatus.PENDING.value, IngestJobStatus.STALE.value]
                    ),
                )
                .values(
                    status=IngestJobStatus.PROCESSING.value,
                    claim_id=claim_id,
                    attempt=record.attempt + 1,
                    updated_at=now,
                    error_message=None,
                )
            )
            if (result.rowcount or 0) != 1:
                return None
            claimed = session.get(IngestJobRecord, record.id)
            return self._to_job(claimed) if claimed is not None else None

    async def renew_claim(self, job_id: str, claim_id: str) -> bool:
        return await asyncio.to_thread(self._renew_claim_sync, job_id, claim_id)

    def _renew_claim_sync(self, job_id: str, claim_id: str) -> bool:
        with self._session() as session:
            result = session.execute(
                update(IngestJobRecord)
                .where(
                    IngestJobRecord.id == job_id,
                    IngestJobRecord.claim_id == claim_id,
                    IngestJobRecord.status == IngestJobStatus.PROCESSING.value,
                )
                .values(updated_at=datetime.now(UTC))
            )
            return (result.rowcount or 0) == 1

    async def mark_stale_jobs(self, stale_before: datetime) -> int:
        return await asyncio.to_thread(self._mark_stale_jobs_sync, stale_before)

    def _mark_stale_jobs_sync(self, stale_before: datetime) -> int:
        with self._session() as session:
            result = session.execute(
                update(IngestJobRecord)
                .where(
                    IngestJobRecord.status == IngestJobStatus.PROCESSING.value,
                    IngestJobRecord.updated_at < stale_before,
                )
                .values(
                    status=IngestJobStatus.STALE.value,
                    claim_id=None,
                    updated_at=datetime.now(UTC),
                )
            )
            return int(result.rowcount or 0)

    async def complete_job(
        self,
        job_id: str,
        claim_id: str,
        *,
        chunk_count: int,
    ) -> bool:
        return await asyncio.to_thread(
            self._complete_job_sync, job_id, claim_id, chunk_count
        )

    def _complete_job_sync(self, job_id: str, claim_id: str, chunk_count: int) -> bool:
        with self._session() as session:
            result = session.execute(
                update(IngestJobRecord)
                .where(
                    IngestJobRecord.id == job_id,
                    IngestJobRecord.claim_id == claim_id,
                    IngestJobRecord.status == IngestJobStatus.PROCESSING.value,
                )
                .values(
                    status=IngestJobStatus.COMPLETED.value,
                    chunk_count=chunk_count,
                    updated_at=datetime.now(UTC),
                    error_message=None,
                )
            )
            return (result.rowcount or 0) == 1

    async def fail_job(
        self,
        job_id: str,
        claim_id: str,
        *,
        error_message: str,
    ) -> bool:
        return await asyncio.to_thread(
            self._fail_job_sync, job_id, claim_id, error_message
        )

    def _fail_job_sync(self, job_id: str, claim_id: str, error_message: str) -> bool:
        with self._session() as session:
            result = session.execute(
                update(IngestJobRecord)
                .where(
                    IngestJobRecord.id == job_id,
                    IngestJobRecord.claim_id == claim_id,
                    IngestJobRecord.status == IngestJobStatus.PROCESSING.value,
                )
                .values(
                    status=IngestJobStatus.FAILED.value,
                    updated_at=datetime.now(UTC),
                    error_message=error_message,
                )
            )
            return (result.rowcount or 0) == 1

    def _to_job(self, record: IngestJobRecord) -> IngestJob:
        return IngestJob(
            id=record.id,
            document_id=record.document_id,
            document_name=record.document_name,
            file_type=record.file_type,
            source_uri=record.source_uri,
            markdown=record.markdown,
            artifact_uri=record.artifact_uri,
            correlation_id=record.correlation_id,
            status=IngestJobStatus(record.status),
            claim_id=record.claim_id,
            attempt=record.attempt,
            chunk_count=record.chunk_count,
            error_message=record.error_message,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
