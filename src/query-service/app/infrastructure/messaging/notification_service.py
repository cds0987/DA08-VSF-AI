from dataclasses import dataclass, field

from app.application.ports import AuthenticatedUser
from app.domain.entities.notification import Notification
from app.domain.repositories.notification_repository import NotificationRepository
from app.infrastructure.db.mock_document_access_repo import can_access_document
from app.infrastructure.sse.connection_manager import ConnectionManager


@dataclass(frozen=True)
class LeaveStatusEvent:
    requester_user_id: str
    request_id: str
    status: str
    rejected_reason: str = ""


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
        repository: NotificationRepository,
        connection_manager: ConnectionManager,
        user_access_profile_repo=None,
    ) -> None:
        self._repository = repository
        self._connection_manager = connection_manager
        self._user_access_profile_repo = user_access_profile_repo

    async def publish_doc_new(self, event: DocNewEvent) -> list[Notification]:
        payload = {
            "type": "notify",
            "event": "doc_new",
            "message": f"Có tài liệu mới: {event.document_name}",
            "doc_id": event.doc_id,
        }
        # Lấy TẤT CẢ user có quyền (kể cả đang offline) để lưu vào DB.
        # Chỉ push SSE cho user đang online. Tránh user offline mất notification khi fetchHistory.
        if self._user_access_profile_repo is not None:
            all_eligible_ids = set(await self._user_access_profile_repo.list_eligible_user_ids(
                event.classification, event.allowed_departments, event.allowed_user_ids,
            ))
        else:
            all_eligible_ids = {u.id for u in self._eligible_online_users(event)}
        online_ids = {u.id for u in self._connection_manager.online_users()}
        delivered: list[Notification] = []
        for user_id in all_eligible_ids:
            notification = await self._repository.save(
                user_id=user_id,
                event="doc_new",
                message=payload["message"],
                doc_id=event.doc_id,
            )
            delivered.append(notification)
            if user_id in online_ids:
                await self._connection_manager.push_to_user(user_id, payload)
        return delivered

    async def publish_leave_status(self, event: LeaveStatusEvent) -> list[Notification]:
        if event.status == "approved":
            message = "Đơn nghỉ phép của bạn đã được duyệt ✅"
            event_type = "leave_approved"
        elif event.status == "cancelled":
            message = "Đơn nghỉ phép của bạn đã bị huỷ 🚫"
            event_type = "leave_cancelled"
        else:
            message = (
                "Đơn nghỉ phép của bạn bị từ chối ❌"
                + (f" — {event.rejected_reason}" if event.rejected_reason else "")
            )
            event_type = "leave_rejected"
        payload = {
            "type": "notify",
            "event": event_type,
            "message": message,
            "request_id": event.request_id,
        }
        notification = await self._repository.save(
            user_id=event.requester_user_id,
            event=event_type,
            message=message,
            doc_id=None,
        )
        await self._connection_manager.push_to_user(event.requester_user_id, payload)
        return [notification]

    async def delete_doc_notifications(self, doc_id: str) -> int:
        return await self._repository.delete_by_doc_id(doc_id)

    def _eligible_online_users(self, event: DocNewEvent) -> list[AuthenticatedUser]:
        return [
            user
            for user in self._connection_manager.online_users()
            if can_access_document(
                user_id=user.id,
                role=user.role,
                department=getattr(user, "department", "") or "",
                account_type=getattr(user, "account_type", "internal") or "internal",
                classification=event.classification,
                allowed_departments=event.allowed_departments,
                allowed_user_ids=event.allowed_user_ids,
            )
        ]
