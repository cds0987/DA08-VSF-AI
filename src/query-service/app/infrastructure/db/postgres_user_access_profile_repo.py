from datetime import datetime

from app.domain.repositories.user_access_profile_repository import (
    UserAccessProfile,
    UserAccessProfileRepository,
)


class PostgresUserAccessProfileRepository(UserAccessProfileRepository):
    """Persists user access profiles to query_svc.user_access_profile (data-schema.md)."""

    def __init__(self, database_url: str) -> None:
        self._database_url = _asyncpg_url(database_url)
        self._pool = None

    async def upsert_profile(
        self,
        user_id: str,
        account_type: str,
        department: str,
        employment_status: str,
        occurred_at: datetime | None = None,
    ) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO query_svc.user_access_profile (
                    user_id,
                    account_type,
                    department,
                    employment_status,
                    updated_at
                )
                VALUES ($1::uuid, $2, $3, $4, COALESCE($5::timestamptz, now()))
                ON CONFLICT (user_id) DO UPDATE SET
                    account_type       = EXCLUDED.account_type,
                    department         = EXCLUDED.department,
                    employment_status  = EXCLUDED.employment_status,
                    updated_at         = EXCLUDED.updated_at
                WHERE query_svc.user_access_profile.updated_at <= EXCLUDED.updated_at
                """,
                user_id,
                account_type,
                department,
                employment_status,
                occurred_at,
            )

    async def get_profile(self, user_id: str) -> UserAccessProfile | None:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT account_type, department, employment_status
                FROM query_svc.user_access_profile
                WHERE user_id = $1::uuid
                """,
                user_id,
            )
        if row is None:
            return None
        return UserAccessProfile(
            user_id=user_id,
            account_type=str(row["account_type"]),
            department=str(row["department"]),
            employment_status=str(row["employment_status"]),
        )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def _get_pool(self):
        if self._pool is None:
            asyncpg = _import_asyncpg()
            self._pool = await asyncpg.create_pool(self._database_url)
        return self._pool


def _asyncpg_url(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _import_asyncpg():
    try:
        import asyncpg
    except ImportError as exc:
        raise RuntimeError("asyncpg is required for Postgres repositories") from exc
    return asyncpg
