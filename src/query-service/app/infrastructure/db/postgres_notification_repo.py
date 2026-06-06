from datetime import timezone

from app.domain.entities.notification import Notification
from app.domain.repositories.notification_repository import NotificationRepository
from app.infrastructure.db.postgres_document_access_repo import _asyncpg_url, _import_asyncpg


class PostgresNotificationRepository(NotificationRepository):
    def __init__(self, database_url: str) -> None:
        self._database_url = _asyncpg_url(database_url)
        self._pool = None

    async def save(
        self,
        user_id: str,
        event: str,
        message: str,
        doc_id: str | None = None,
    ) -> Notification:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO query_svc.notifications (user_id, event, message, doc_id)
                VALUES ($1::uuid, $2, $3, $4::uuid)
                RETURNING id, user_id, event, message, doc_id, is_read, created_at
                """,
                user_id,
                event,
                message,
                doc_id,
            )
        return _notification_from_row(row)

    async def list_history(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
        unread_only: bool = False,
    ) -> list[Notification]:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT id, user_id, event, message, doc_id, is_read, created_at
                FROM query_svc.notifications
                WHERE user_id = $1::uuid AND ($2::bool = false OR is_read = false)
                ORDER BY created_at DESC
                LIMIT $3 OFFSET $4
                """,
                user_id,
                unread_only,
                limit,
                offset,
            )
        return [_notification_from_row(row) for row in rows]

    async def total_for_user(self, user_id: str, unread_only: bool = False) -> int:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            return int(
                await connection.fetchval(
                    """
                    SELECT count(*)
                    FROM query_svc.notifications
                    WHERE user_id = $1::uuid AND ($2::bool = false OR is_read = false)
                    """,
                    user_id,
                    unread_only,
                )
            )

    async def unread_count(self, user_id: str) -> int:
        return await self.total_for_user(user_id, unread_only=True)

    async def mark_read(self, notification_id: str) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            await connection.execute(
                "UPDATE query_svc.notifications SET is_read = true WHERE id = $1::uuid",
                notification_id,
            )

    async def mark_read_for_user(self, user_id: str, notification_id: str) -> Notification | None:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                UPDATE query_svc.notifications
                SET is_read = true
                WHERE id = $1::uuid AND user_id = $2::uuid
                RETURNING id, user_id, event, message, doc_id, is_read, created_at
                """,
                notification_id,
                user_id,
            )
        return _notification_from_row(row) if row else None

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def _get_pool(self):
        if self._pool is None:
            asyncpg = _import_asyncpg()
            self._pool = await asyncpg.create_pool(self._database_url)
        return self._pool


def _notification_from_row(row) -> Notification:
    created_at = row["created_at"]
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return Notification(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        event=str(row["event"]),
        message=str(row["message"]),
        doc_id=str(row["doc_id"]) if row["doc_id"] else None,
        is_read=bool(row["is_read"]),
        created_at=created_at,
    )
