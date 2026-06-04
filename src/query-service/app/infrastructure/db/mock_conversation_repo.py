from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from uuid import uuid4

from app.domain.entities.conversation import ConversationContext, Message
from app.domain.repositories.conversation_repository import ConversationRepository


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
    summary: str | None = None
    messages: list[StoredMessage] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class InMemoryConversationRepository(ConversationRepository):
    def __init__(self) -> None:
        self._by_user: dict[str, StoredConversation] = {}

    async def get_context(self, user_id: str, recent_k: int = 5) -> ConversationContext:
        conversation = self._ensure_conversation(user_id)
        recent_messages = conversation.messages[-recent_k * 2 :]
        return ConversationContext(
            summary=conversation.summary,
            recent_messages=[
                Message(role=item.role, content=item.content, created_at=item.created_at)
                for item in recent_messages
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
        conversation = self._ensure_conversation(user_id)
        message = StoredMessage(
            id=str(uuid4()),
            session_id=session_id,
            user_id=user_id,
            role=role,
            content=content,
            created_at=datetime.now(UTC),
            sources=sources or [],
            latency_ms=latency_ms,
        )
        conversation.messages.append(message)
        conversation.updated_at = datetime.now(UTC)
        return message

    async def update_summary(self, user_id: str, summary: str) -> None:
        conversation = self._ensure_conversation(user_id)
        conversation.summary = summary
        conversation.updated_at = datetime.now(UTC)

    async def clear_history(self, user_id: str) -> None:
        self._by_user.pop(user_id, None)

    async def save_feedback(self, session_id: str, score: int) -> None:
        recorded = await self.record_feedback(session_id, score)
        if not recorded:
            raise ValueError("Session not found")

    async def list_messages(self, user_id: str, limit: int = 20, offset: int = 0) -> list[StoredMessage]:
        conversation = self._ensure_conversation(user_id)
        ordered = sorted(conversation.messages, key=lambda item: item.created_at)
        return ordered[offset : offset + limit]

    async def record_feedback(self, session_id: str, score: int) -> bool:
        for conversation in self._by_user.values():
            for message in reversed(conversation.messages):
                if message.session_id == session_id and message.role == "assistant":
                    message.feedback = score
                    return True
        return False

    async def metrics(self, from_date: date | None = None, to_date: date | None = None) -> dict:
        user_messages: list[StoredMessage] = []
        assistant_messages: list[StoredMessage] = []
        for conversation in self._by_user.values():
            for message in conversation.messages:
                message_date = message.created_at.date()
                if from_date and message_date < from_date:
                    continue
                if to_date and message_date > to_date:
                    continue
                if message.role == "user":
                    user_messages.append(message)
                elif message.role == "assistant":
                    assistant_messages.append(message)

        by_day_counts: dict[str, int] = defaultdict(int)
        for message in user_messages:
            by_day_counts[message.created_at.date().isoformat()] += 1

        feedback_values = [message.feedback for message in assistant_messages if message.feedback in (1, -1)]
        up = feedback_values.count(1)
        down = feedback_values.count(-1)
        rate = round(up / (up + down), 2) if up + down else 0.0

        top = Counter(message.content for message in user_messages)
        return {
            "total_questions": len(user_messages),
            "by_day": [
                {"date": day, "count": count}
                for day, count in sorted(by_day_counts.items())
            ],
            "feedback": {"up": up, "down": down, "rate": rate},
            "top_questions": [
                {"question": question, "count": count}
                for question, count in top.most_common(10)
            ],
        }

    def reset(self) -> None:
        self._by_user.clear()

    def _ensure_conversation(self, user_id: str) -> StoredConversation:
        if user_id not in self._by_user:
            self._by_user[user_id] = StoredConversation(id=str(uuid4()), user_id=user_id)
        return self._by_user[user_id]
