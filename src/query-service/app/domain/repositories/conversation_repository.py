from abc import ABC, abstractmethod

from app.domain.entities.conversation import ConversationContext


class ConversationRepository(ABC):
    @abstractmethod
    async def get_context(self, user_id: str, recent_k: int = 5) -> ConversationContext:
        """Return the summary plus recent messages for LLM context."""

    @abstractmethod
    async def save_message(self, user_id: str, role: str, content: str) -> None:
        """Persist one message in the user's conversation history."""

    @abstractmethod
    async def update_summary(self, user_id: str, summary: str) -> None:
        """Update the compressed summary for older turns."""

    @abstractmethod
    async def clear_history(self, user_id: str) -> None:
        """Clear all messages and summary for one user."""

    @abstractmethod
    async def save_feedback(self, session_id: str, score: int) -> None:
        """Persist feedback for the assistant answer identified by session_id."""
