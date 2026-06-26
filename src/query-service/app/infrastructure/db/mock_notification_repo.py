from datetime import datetime, timezone
from uuid import uuid4

from app.domain.entities.notification import Notification
from app.domain.repositories.notification_repository import NotificationRepository


class InMemoryNotificationRepository(NotificationRepository):
    def __init__(self) -> None:
        self._items: dict[str, list[Notification]] = {}

    async def save(
        self,
        user_id: str,
        event: str,
        message: str,
        doc_id: str | None = None,
    ) -> Notification:
        notification = Notification(
            id=str(uuid4()),
            user_id=user_id,
            event=event,
            message=message,
            doc_id=doc_id,
            is_read=False,
            created_at=datetime.now(timezone.utc),
        )
        self._items.setdefault(user_id, []).append(notification)
        return notification

    async def list_history(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
        unread_only: bool = False,
    ) -> list[Notification]:
        items = list(self._items.get(user_id, []))
        if unread_only:
            items = [item for item in items if not item.is_read]
        ordered = sorted(items, key=lambda item: item.created_at, reverse=True)
        return ordered[offset : offset + limit]

    async def total_for_user(self, user_id: str, unread_only: bool = False) -> int:
        items = list(self._items.get(user_id, []))
        if unread_only:
            items = [item for item in items if not item.is_read]
        return len(items)

    async def unread_count(self, user_id: str) -> int:
        return sum(1 for item in self._items.get(user_id, []) if not item.is_read)

    async def mark_read(self, notification_id: str) -> None:
        for items in self._items.values():
            for item in items:
                if item.id == notification_id:
                    item.is_read = True
                    return
        raise ValueError("Notification not found")

    async def mark_read_for_user(self, user_id: str, notification_id: str) -> Notification | None:
        for item in self._items.get(user_id, []):
            if item.id == notification_id:
                item.is_read = True
                return item
        return None

    async def delete_by_user_id(self, user_id: str) -> int:
        items = self._items.pop(user_id, [])
        return len(items)

    async def delete_by_doc_id(self, doc_id: str) -> int:
        count = 0
        for user_id in self._items:
            before = len(self._items[user_id])
            self._items[user_id] = [n for n in self._items[user_id] if n.doc_id != doc_id]
            count += before - len(self._items[user_id])
        return count

    async def delete_by_id(self, user_id: str, notification_id: str) -> bool:
        items = self._items.get(user_id, [])
        before = len(items)
        self._items[user_id] = [n for n in items if n.id != notification_id]
        return len(self._items[user_id]) < before

    def reset(self) -> None:
        self._items.clear()
