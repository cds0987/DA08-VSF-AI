from __future__ import annotations

import logging
from typing import Any

from app.domain.entities.user import User
from app.infrastructure.messaging.user_event_publisher import UserEventPublisher

logger = logging.getLogger(__name__)


def _role_value(role: object) -> str:
    value = getattr(role, "value", None)
    return str(value if value is not None else role)


def user_to_payload(user: User) -> dict[str, Any]:
    return {
        "user_id": user.id,
        "email": user.email,
        "role": _role_value(user.role),
        "department": user.department,
        "account_type": user.account_type,
        "is_active": user.is_active,
    }


class NatsUserEventEmitter:
    """Adapter best-effort cho UserEventEmitter Protocol: lỗi publish CHỈ log warning,
    KHÔNG raise -> không làm hỏng nghiệp vụ. Sync vẫn được lưới an toàn bởi backfill +
    hr lazy auto-create."""

    def __init__(self, publisher: UserEventPublisher) -> None:
        self._publisher = publisher

    async def emit(self, subject: str, user: User) -> None:
        try:
            await self._publisher.publish_user_event(subject, user_to_payload(user))
        except Exception as exc:  # noqa: BLE001
            logger.warning("user event %s publish failed (best-effort): %s", subject, exc)
