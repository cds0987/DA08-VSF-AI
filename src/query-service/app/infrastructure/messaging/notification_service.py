from dataclasses import dataclass, field

from app.domain.entities.notification import Notification
from app.infrastructure.auth.auth_service import AuthenticatedUser
from app.infrastructure.db.mock_data import mock_users
from app.infrastructure.db.mock_document_access_repo import can_access_document
from app.infrastructure.db.mock_notification_repo import InMemoryNotificationRepository
from app.infrastructure.sse.connection_manager import ConnectionManager


@dataclass(frozen=True)
class DocNewEvent:
    doc_id: str
    document_name: str
    classification: str
    allowed_departments: list[str] = field(default_factory=list)
    allowed_user_ids: list[str] = field(default_factory=list)


class NotificationService:
    def __init__(
        self,
        repository: InMemoryNotificationRepository,
        connection_manager: ConnectionManager,
    ) -> None:
        self._repository = repository
        self._connection_manager = connection_manager

    async def publish_doc_new(self, event: DocNewEvent) -> list[Notification]:
        payload = {
            "type": "notify",
            "event": "doc_new",
            "message": f"Có tài liệu mới: {event.document_name}",
            "doc_id": event.doc_id,
        }
        delivered: list[Notification] = []
        for user in self._eligible_mock_users(event):
            notification = await self._repository.save(
                user_id=user.id,
                event="doc_new",
                message=payload["message"],
                doc_id=event.doc_id,
            )
            delivered.append(notification)
            await self._connection_manager.push_to_user(user.id, payload)
        return delivered

    @staticmethod
    def _eligible_mock_users(event: DocNewEvent) -> list[AuthenticatedUser]:
        return [
            user
            for user in mock_users()
            if can_access_document(
                user_id=user.id,
                role=user.role,
                department=user.department,
                classification=event.classification,
                allowed_departments=event.allowed_departments,
                allowed_user_ids=event.allowed_user_ids,
            )
        ]
