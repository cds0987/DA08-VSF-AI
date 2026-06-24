import os
from datetime import datetime

from app.domain.repositories.document_access_repository import DocumentAccessRepository
from app.infrastructure.db.dsn import to_asyncpg_dsn
from app.infrastructure.db.mock_document_access_repo import can_access_document


class PostgresDocumentAccessRepository(DocumentAccessRepository):
    def __init__(self, database_url: str) -> None:
        self._database_url = to_asyncpg_dsn(database_url)
        self._pool = None

    async def get_allowed_doc_ids(
        self,
        user_id: str,
        role: str,
        department: str,
        account_type: str = "internal",
    ) -> list[str]:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT document_id, classification, allowed_departments, allowed_user_ids
                FROM query_svc.document_access
                """
            )
        return [
            str(row["document_id"])
            for row in rows
            if can_access_document(
                user_id=user_id,
                role=role,
                department=department,
                account_type=account_type,
                classification=str(row["classification"]),
                allowed_departments=list(row["allowed_departments"] or []),
                allowed_user_ids=list(row["allowed_user_ids"] or []),
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
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO query_svc.document_access (
                    document_id,
                    classification,
                    allowed_departments,
                    allowed_user_ids,
                    updated_at
                )
                VALUES ($1::uuid, $2, $3::text[], $4::text[], COALESCE($5::timestamptz, now()))
                ON CONFLICT (document_id) DO UPDATE SET
                    classification = EXCLUDED.classification,
                    allowed_departments = EXCLUDED.allowed_departments,
                    allowed_user_ids = EXCLUDED.allowed_user_ids,
                    updated_at = EXCLUDED.updated_at
                WHERE query_svc.document_access.updated_at <= EXCLUDED.updated_at
                """,
                document_id,
                classification,
                allowed_departments,
                allowed_user_ids,
                occurred_at,
            )

    async def delete_access(self, document_id: str) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            await connection.execute(
                "DELETE FROM query_svc.document_access WHERE document_id = $1::uuid",
                document_id,
            )

    async def rename_department(self, old_name: str, new_name: str) -> int:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            result = await connection.execute(
                """
                UPDATE query_svc.document_access
                SET allowed_departments = array_replace(allowed_departments, $1, $2),
                    updated_at = now()
                WHERE $1 = ANY(allowed_departments)
                """,
                old_name,
                new_name,
            )
        parts = (result or "").split()
        return int(parts[-1]) if parts and parts[-1].isdigit() else 0

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def _get_pool(self):
        if self._pool is None:
            asyncpg = _import_asyncpg()
            self._pool = await asyncpg.create_pool(
                self._database_url,
                min_size=int(os.environ.get("DB_POOL_MIN_SIZE", "1")),
                max_size=int(os.environ.get("DB_POOL_MAX_SIZE", "10")),
            )
        return self._pool


def _import_asyncpg():
    try:
        import asyncpg
    except ImportError as exc:
        raise RuntimeError("asyncpg is required for Postgres repositories") from exc
    return asyncpg
