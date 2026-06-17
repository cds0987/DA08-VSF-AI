from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
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
    title: str = "Untitled chat"
    summary: str | None = None
    messages: list[StoredMessage] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class InMemoryConversationRepository(ConversationRepository):
    def __init__(self) -> None:
        self._by_id: dict[str, StoredConversation] = {}

    async def get_context(
        self,
        user_id: str,
        recent_k: int = 5,
        conversation_id: str | None = None,
    ) -> ConversationContext:
        if conversation_id:
            existing = self._by_id.get(conversation_id)
            if existing is not None and existing.user_id != user_id:
                raise PermissionError("Conversation belongs to another user")
        conversation = self._find_conversation(user_id, conversation_id)
        if conversation is None:
            return ConversationContext(summary=None, recent_messages=[])
        recent_messages = conversation.messages[-recent_k * 2 :]
        return ConversationContext(
            summary=conversation.summary,
            recent_messages=[
                Message(role=item.role, content=item.content, created_at=item.created_at,
                        sources=item.sources)
                for item in recent_messages
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
        conversation = self._ensure_conversation(
            user_id,
            conversation_id,
            conversation_title,
            create_if_missing=create_if_missing,
        )
        if conversation is None:
            return None
        message = StoredMessage(
            id=str(uuid4()),
            session_id=session_id,
            user_id=user_id,
            role=role,
            content=content,
            created_at=datetime.now(timezone.utc),
            sources=sources or [],
            latency_ms=latency_ms,
        )
        conversation.messages.append(message)
        conversation.updated_at = datetime.now(timezone.utc)
        return message

    async def update_summary(
        self,
        user_id: str,
        summary: str,
        conversation_id: str | None = None,
    ) -> None:
        conversation = self._ensure_conversation(user_id, conversation_id)
        conversation.summary = summary
        conversation.updated_at = datetime.now(timezone.utc)

    async def clear_history(self, user_id: str) -> None:
        self._by_id = {
            key: conversation
            for key, conversation in self._by_id.items()
            if conversation.user_id != user_id
        }

    async def list_conversations(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[StoredConversation]:
        conversations = sorted(
            (
                conversation
                for conversation in self._by_id.values()
                if conversation.user_id == user_id and conversation.messages
            ),
            key=lambda item: item.updated_at,
            reverse=True,
        )
        return conversations[offset : offset + limit]

    async def get_conversation(
        self,
        user_id: str,
        conversation_id: str,
    ) -> StoredConversation | None:
        conversation = self._by_id.get(conversation_id)
        if conversation is None or conversation.user_id != user_id:
            return None
        return conversation

    async def rename_conversation(
        self,
        user_id: str,
        conversation_id: str,
        title: str,
    ) -> bool:
        conversation = await self.get_conversation(user_id, conversation_id)
        if conversation is None:
            return False
        conversation.title = title
        conversation.updated_at = datetime.now(timezone.utc)
        return True

    async def delete_conversation(self, user_id: str, conversation_id: str) -> bool:
        conversation = await self.get_conversation(user_id, conversation_id)
        if conversation is None:
            return False
        del self._by_id[conversation_id]
        return True

    async def save_feedback(self, session_id: str, score: int) -> None:
        recorded = await self.record_feedback(session_id, score)
        if not recorded:
            raise ValueError("Session not found")

    async def list_messages(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
        conversation_id: str | None = None,
    ) -> list[StoredMessage]:
        conversation = self._find_conversation(user_id, conversation_id)
        if conversation is None:
            return []
        ordered = sorted(conversation.messages, key=lambda item: item.created_at)
        end = max(0, len(ordered) - offset)
        start = max(0, end - limit)
        return ordered[start:end]

    async def record_feedback(self, session_id: str, score: int) -> bool:
        for conversation in self._by_id.values():
            for message in reversed(conversation.messages):
                if message.session_id == session_id and message.role == "assistant":
                    message.feedback = score
                    return True
        return False

    async def metrics(self, from_date: date | None = None, to_date: date | None = None) -> dict:
        user_messages: list[StoredMessage] = []
        assistant_messages: list[StoredMessage] = []
        for conversation in self._by_id.values():
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

        feedback_values = [
            message.feedback
            for message in assistant_messages
            if message.feedback in (1, -1)
        ]
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
        self._by_id.clear()

    def _find_conversation(
        self,
        user_id: str,
        conversation_id: str | None,
    ) -> StoredConversation | None:
        if conversation_id:
            conversation = self._by_id.get(conversation_id)
            if conversation is None or conversation.user_id != user_id:
                return None
            return conversation
        candidates = [
            conversation
            for conversation in self._by_id.values()
            if conversation.user_id == user_id
        ]
        return max(candidates, key=lambda item: item.updated_at) if candidates else None

    def _ensure_conversation(
        self,
        user_id: str,
        conversation_id: str | None = None,
        title: str | None = None,
        create_if_missing: bool = True,
    ) -> StoredConversation | None:
        conversation = self._find_conversation(user_id, conversation_id)
        if conversation is not None:
            return conversation
        if not create_if_missing:
            return None
        new_id = conversation_id or str(uuid4())
        if new_id in self._by_id:
            raise PermissionError("Conversation belongs to another user")
        conversation = StoredConversation(
            id=new_id,
            user_id=user_id,
            title=(title or "Untitled chat").strip() or "Untitled chat",
        )
        self._by_id[new_id] = conversation
        return conversation
