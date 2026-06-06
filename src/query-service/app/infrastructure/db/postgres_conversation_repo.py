from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import json

from app.domain.entities.conversation import ConversationContext, Message
from app.domain.repositories.conversation_repository import ConversationRepository
from app.infrastructure.db.postgres_document_access_repo import _asyncpg_url, _import_asyncpg


@dataclass
class StoredMessage:
    id: str
    session_id: str | None
    user_id: str
    role: str
    content: str
    created_at: datetime
    sources: list[dict] = field(default_factory=list)
    latency_ms: int | None = None
    feedback: int | None = None


class PostgresConversationRepository(ConversationRepository):
    def __init__(self, database_url: str) -> None:
        self._database_url = _asyncpg_url(database_url)
        self._pool = None

    async def get_context(self, user_id: str, recent_k: int = 5) -> ConversationContext:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            conversation = await self._ensure_conversation(connection, user_id)
            rows = await connection.fetch(
                """
                SELECT role, content, created_at
                FROM query_svc.messages
                WHERE conversation_id = $1::uuid
                ORDER BY created_at DESC
                LIMIT $2
                """,
                conversation["id"],
                recent_k * 2,
            )
        return ConversationContext(
            summary=conversation["summary"],
            recent_messages=[
                Message(
                    role=str(row["role"]),
                    content=str(row["content"]),
                    created_at=_aware(row["created_at"]),
                )
                for row in reversed(rows)
            ],
        )

    async def save_message(self, user_id: str, role: str, content: str) -> None:
        await self.save_message_detail(user_id=user_id, role=role, content=content)

    async def save_message_detail(
        self,
        user_id: str,
        role: str,
        content: str,
        session_id: str | None = None,
        sources: list[dict] | None = None,
        latency_ms: int | None = None,
    ) -> StoredMessage:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            conversation = await self._ensure_conversation(connection, user_id)
            row = await connection.fetchrow(
                """
                INSERT INTO query_svc.messages (
                    conversation_id,
                    user_id,
                    role,
                    content,
                    session_id,
                    sources,
                    latency_ms
                )
                VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6::jsonb, $7)
                RETURNING id, session_id, user_id, role, content, created_at, sources, latency_ms, feedback
                """,
                conversation["id"],
                user_id,
                role,
                content,
                session_id,
                json.dumps(sources or []),
                latency_ms,
            )
            await connection.execute(
                "UPDATE query_svc.conversations SET updated_at = now() WHERE id = $1::uuid",
                conversation["id"],
            )
        return _stored_message_from_row(row)

    async def update_summary(self, user_id: str, summary: str) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            conversation = await self._ensure_conversation(connection, user_id)
            await connection.execute(
                """
                UPDATE query_svc.conversations
                SET summary = $2, updated_at = now()
                WHERE id = $1::uuid
                """,
                conversation["id"],
                summary,
            )

    async def clear_history(self, user_id: str) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            await connection.execute(
                "DELETE FROM query_svc.conversations WHERE user_id = $1::uuid",
                user_id,
            )

    async def save_feedback(self, session_id: str, score: int) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                UPDATE query_svc.messages
                SET feedback = $2
                WHERE session_id = $1 AND role = 'assistant'
                RETURNING id
                """,
                session_id,
                score,
            )
        if row is None:
            raise ValueError("Session not found")

    async def list_messages(self, user_id: str, limit: int = 20, offset: int = 0) -> list[StoredMessage]:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            conversation = await self._ensure_conversation(connection, user_id)
            rows = await connection.fetch(
                """
                SELECT id, session_id, user_id, role, content, created_at, sources, latency_ms, feedback
                FROM query_svc.messages
                WHERE conversation_id = $1::uuid
                ORDER BY created_at ASC
                LIMIT $2 OFFSET $3
                """,
                conversation["id"],
                limit,
                offset,
            )
        return [_stored_message_from_row(row) for row in rows]

    async def metrics(self, from_date: date | None = None, to_date: date | None = None) -> dict:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            user_rows = await connection.fetch(
                """
                SELECT content, created_at
                FROM query_svc.messages
                WHERE role = 'user'
                  AND ($1::date IS NULL OR created_at::date >= $1::date)
                  AND ($2::date IS NULL OR created_at::date <= $2::date)
                """,
                from_date,
                to_date,
            )
            feedback_rows = await connection.fetch(
                """
                SELECT feedback
                FROM query_svc.messages
                WHERE role = 'assistant'
                  AND feedback IN (1, -1)
                  AND ($1::date IS NULL OR created_at::date >= $1::date)
                  AND ($2::date IS NULL OR created_at::date <= $2::date)
                """,
                from_date,
                to_date,
            )

        by_day: dict[str, int] = {}
        top = Counter()
        for row in user_rows:
            created_at = _aware(row["created_at"])
            day = created_at.date().isoformat()
            by_day[day] = by_day.get(day, 0) + 1
            top[str(row["content"])] += 1

        feedback_values = [int(row["feedback"]) for row in feedback_rows]
        up = feedback_values.count(1)
        down = feedback_values.count(-1)
        rate = round(up / (up + down), 2) if up + down else 0.0
        return {
            "total_questions": len(user_rows),
            "by_day": [
                {"date": day, "count": count}
                for day, count in sorted(by_day.items())
            ],
            "feedback": {"up": up, "down": down, "rate": rate},
            "top_questions": [
                {"question": question, "count": count}
                for question, count in top.most_common(10)
            ],
        }

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def _get_pool(self):
        if self._pool is None:
            asyncpg = _import_asyncpg()
            self._pool = await asyncpg.create_pool(self._database_url)
        return self._pool

    async def _ensure_conversation(self, connection, user_id: str):
        return await connection.fetchrow(
            """
            INSERT INTO query_svc.conversations (user_id)
            VALUES ($1::uuid)
            ON CONFLICT (user_id) DO UPDATE SET updated_at = query_svc.conversations.updated_at
            RETURNING id, user_id, summary
            """,
            user_id,
        )


def _stored_message_from_row(row) -> StoredMessage:
    sources = row["sources"] or []
    if isinstance(sources, str):
        sources = json.loads(sources)
    return StoredMessage(
        id=str(row["id"]),
        session_id=str(row["session_id"]) if row["session_id"] else None,
        user_id=str(row["user_id"]),
        role=str(row["role"]),
        content=str(row["content"]),
        created_at=_aware(row["created_at"]),
        sources=list(sources),
        latency_ms=row["latency_ms"],
        feedback=row["feedback"],
    )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
