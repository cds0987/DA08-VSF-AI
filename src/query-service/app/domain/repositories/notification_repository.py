from abc import ABC, abstractmethod

from app.domain.entities.notification import Notification


class NotificationRepository(ABC):
    @abstractmethod
    async def save(
        self,
        user_id: str,
        event: str,
        message: str,
        doc_id: str | None,
    ) -> Notification:
        """Persist a notification for Notification Center history."""

    @abstractmethod
    async def list_history(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
        unread_only: bool = False,
    ) -> list[Notification]:
        """Return notification history for one user."""

    @abstractmethod
    async def unread_count(self, user_id: str) -> int:
        """Return unread notification count for one user."""

    @abstractmethod
    async def total_for_user(self, user_id: str, unread_only: bool = False) -> int:
        """Return total notification count for one user."""

    @abstractmethod
    async def mark_read(self, notification_id: str) -> None:
        """Mark one notification as read."""

    @abstractmethod
    async def mark_read_for_user(self, user_id: str, notification_id: str) -> Notification | None:
        """Mark one notification as read if it belongs to the user."""
