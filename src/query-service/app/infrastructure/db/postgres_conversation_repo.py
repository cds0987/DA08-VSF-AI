from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import json

from app.domain.entities.conversation import ConversationContext, Message
from app.domain.repositories.conversation_repository import ConversationRepository
from app.infrastructure.db.dsn import to_asyncpg_dsn
from app.infrastructure.db.postgres_document_access_repo import _import_asyncpg


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


@dataclass
class StoredConversation:
    id: str
    user_id: str
    title: str
    summary: str | None
    created_at: datetime
    updated_at: datetime


class PostgresConversationRepository(ConversationRepository):
    def __init__(self, database_url: str) -> None:
        self._database_url = to_asyncpg_dsn(database_url)
        self._pool = None

    async def get_context(
        self,
        user_id: str,
        recent_k: int = 5,
        conversation_id: str | None = None,
    ) -> ConversationContext:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            if conversation_id:
                conversation = await connection.fetchrow(
                    """
                    SELECT id, user_id, summary
                    FROM query_svc.conversations
                    WHERE id = $1::uuid
                    """,
                    conversation_id,
                )
                if conversation is not None and str(conversation["user_id"]) != user_id:
                    raise PermissionError("Conversation belongs to another user")
            else:
                conversation = await self._latest_conversation(connection, user_id)

            if conversation is None:
                return ConversationContext(summary=None, recent_messages=[])

            rows = await connection.fetch(
                """
                SELECT role, content, created_at, sources
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
                    sources=json.loads(row["sources"]) if isinstance(row["sources"], str)
                            else (row["sources"] or []),
                )
                for row in reversed(rows)
            ],
        )

    async def save_message(
        self,
        user_id: str,
        role: str,
        content: str,
        conversation_id: str | None = None,
    ) -> None:
        await self.save_message_detail(
            user_id=user_id,
            role=role,
            content=content,
            conversation_id=conversation_id,
        )

    async def save_message_detail(
        self,
        user_id: str,
        role: str,
        content: str,
        conversation_id: str | None = None,
        conversation_title: str | None = None,
        session_id: str | None = None,
        sources: list[dict] | None = None,
        latency_ms: int | None = None,
        create_if_missing: bool = True,
    ) -> StoredMessage | None:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            conversation = await self._ensure_conversation(
                connection,
                user_id,
                conversation_id,
                conversation_title,
                create_if_missing=create_if_missing,
            )
            if conversation is None:
                return None
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
                RETURNING id, session_id, user_id, role, content, created_at,
                          sources, latency_ms, feedback
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

    async def update_summary(
        self,
        user_id: str,
        summary: str,
        conversation_id: str | None = None,
    ) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            conversation = await self._ensure_conversation(
                connection,
                user_id,
                conversation_id,
            )
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

    async def list_conversations(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[StoredConversation]:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT id, user_id, title, summary, created_at, updated_at
                FROM query_svc.conversations
                WHERE user_id = $1::uuid
                  AND EXISTS (
                      SELECT 1
                      FROM query_svc.messages
                      WHERE conversation_id = query_svc.conversations.id
                  )
                ORDER BY updated_at DESC
                LIMIT $2 OFFSET $3
                """,
                user_id,
                limit,
                offset,
            )
        return [_stored_conversation_from_row(row) for row in rows]

    async def get_conversation(
        self,
        user_id: str,
        conversation_id: str,
    ) -> StoredConversation | None:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT id, user_id, title, summary, created_at, updated_at
                FROM query_svc.conversations
                WHERE id = $1::uuid AND user_id = $2::uuid
                """,
                conversation_id,
                user_id,
            )
        return _stored_conversation_from_row(row) if row else None

    async def rename_conversation(
        self,
        user_id: str,
        conversation_id: str,
        title: str,
    ) -> bool:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            result = await connection.execute(
                """
                UPDATE query_svc.conversations
                SET title = $3, updated_at = now()
                WHERE id = $1::uuid AND user_id = $2::uuid
                """,
                conversation_id,
                user_id,
                title,
            )
        return result == "UPDATE 1"

    async def delete_conversation(self, user_id: str, conversation_id: str) -> bool:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            result = await connection.execute(
                """
                DELETE FROM query_svc.conversations
                WHERE id = $1::uuid AND user_id = $2::uuid
                """,
                conversation_id,
                user_id,
            )
        return result == "DELETE 1"

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

    async def list_messages(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
        conversation_id: str | None = None,
    ) -> list[StoredMessage]:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            if conversation_id is None:
                conversation = await self._latest_conversation(connection, user_id)
                if conversation is None:
                    return []
                conversation_id = str(conversation["id"])
            rows = await connection.fetch(
                """
                SELECT *
                FROM (
                    SELECT message.id, message.session_id, message.user_id, message.role,
                           message.content, message.created_at, message.sources,
                           message.latency_ms, message.feedback
                    FROM query_svc.messages AS message
                    JOIN query_svc.conversations AS conversation
                      ON conversation.id = message.conversation_id
                    WHERE message.conversation_id = $1::uuid
                      AND conversation.user_id = $2::uuid
                    ORDER BY message.created_at DESC
                    LIMIT $3 OFFSET $4
                ) AS recent_messages
                ORDER BY created_at ASC
                """,
                conversation_id,
                user_id,
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

    async def _latest_conversation(self, connection, user_id: str):
        return await connection.fetchrow(
            """
            SELECT id, user_id, title, summary, created_at, updated_at
            FROM query_svc.conversations
            WHERE user_id = $1::uuid
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            user_id,
        )

    async def _ensure_conversation(
        self,
        connection,
        user_id: str,
        conversation_id: str | None = None,
        title: str | None = None,
        create_if_missing: bool = True,
    ):
        if conversation_id is None:
            existing = await self._latest_conversation(connection, user_id)
            if existing is not None:
                return existing
            if not create_if_missing:
                return None
            return await connection.fetchrow(
                """
                INSERT INTO query_svc.conversations (user_id, title)
                VALUES ($1::uuid, $2)
                RETURNING id, user_id, title, summary, created_at, updated_at
                """,
                user_id,
                _clean_title(title),
            )

        existing = await connection.fetchrow(
            """
            SELECT id, user_id, title, summary, created_at, updated_at
            FROM query_svc.conversations
            WHERE id = $1::uuid
            """,
            conversation_id,
        )
        if existing is not None:
            if str(existing["user_id"]) != user_id:
                raise PermissionError("Conversation belongs to another user")
            return existing

        if not create_if_missing:
            return None

        inserted = await connection.fetchrow(
            """
            INSERT INTO query_svc.conversations (id, user_id, title)
            VALUES ($1::uuid, $2::uuid, $3)
            ON CONFLICT (id) DO NOTHING
            RETURNING id, user_id, title, summary, created_at, updated_at
            """,
            conversation_id,
            user_id,
            _clean_title(title),
        )
        if inserted is not None:
            return inserted

        existing = await connection.fetchrow(
            """
            SELECT id, user_id, title, summary, created_at, updated_at
            FROM query_svc.conversations
            WHERE id = $1::uuid
            """,
            conversation_id,
        )
        if existing is None or str(existing["user_id"]) != user_id:
            raise PermissionError("Conversation belongs to another user")
        return existing


def _clean_title(title: str | None) -> str:
    value = (title or "Untitled chat").strip()
    return value[:120] or "Untitled chat"


def _stored_conversation_from_row(row) -> StoredConversation:
    return StoredConversation(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        title=str(row["title"]),
        summary=str(row["summary"]) if row["summary"] else None,
        created_at=_aware(row["created_at"]),
        updated_at=_aware(row["updated_at"]),
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
