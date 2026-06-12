from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

from app.core.config import HrSettings
from app.domain.repositories.hr_repository import HrRepository

logger = logging.getLogger("hr-service.user_events")

USER_EVENT_SUBJECTS = ("user.created", "user.updated", "user.deactivated")
STREAM_NAME = "USER_EVENTS"
DURABLE = "HR_USER_LIFECYCLE"


async def handle_user_event(subject: str, payload: dict, repo: HrRepository) -> None:
    """Áp event vòng đời user vào hồ sơ HR. Idempotent (upsert + ON CONFLICT). Tách
    riêng khỏi NATS để test nhanh, không nuốt lỗi (lỗi -> raise cho caller nak/retry)."""
    user_id = str(payload["user_id"]).strip()
    if not user_id:
        raise ValueError("user event missing user_id")
    email = str(payload.get("email", ""))
    department = str(payload.get("department", ""))
    is_active = bool(payload.get("is_active", subject != "user.deactivated"))

    await repo.upsert_employee_from_user(user_id, email, department, is_active)
    if is_active:
        # User đang hoạt động -> đảm bảo có hồ sơ phép mặc định.
        await repo.ensure_leave_balance(user_id)


@dataclass
class SubscriberHandle:
    connection: object | None

    async def close(self) -> None:
        if self.connection is not None:
            await self.connection.drain()


async def start_user_events_subscriber(
    settings: HrSettings,
    repo_factory,
) -> SubscriberHandle:
    """Best-effort: lỗi kết nối CHỈ log warning + trả handle rỗng, KHÔNG crash service.
    Sync vẫn được lưới an toàn bởi hr lazy auto-create."""
    if not settings.user_events_enabled:
        logger.info("user_events subscriber disabled")
        return SubscriberHandle(connection=None)
    try:
        import nats
    except ImportError:
        logger.warning("nats-py not installed; user_events subscriber not started")
        return SubscriberHandle(connection=None)

    try:
        nc = await nats.connect(settings.nats_url)

        async def _cb(message) -> None:
            try:
                payload = json.loads(message.data.decode("utf-8"))
                repo = repo_factory()
                try:
                    await handle_user_event(message.subject, payload, repo)
                finally:
                    await repo.aclose()
                if hasattr(message, "ack"):
                    await message.ack()
            except Exception:
                # Log đầy đủ stacktrace (không nuốt) rồi nak để JetStream redeliver.
                logger.exception("failed to handle user event")
                if hasattr(message, "nak"):
                    await message.nak()

        if settings.nats_jetstream_enabled:
            js = nc.jetstream()
            for subject in USER_EVENT_SUBJECTS:
                await js.subscribe(subject, durable=f"{DURABLE}_{subject.replace('.', '_')}", cb=_cb)
        else:
            for subject in USER_EVENT_SUBJECTS:
                await nc.subscribe(subject, cb=_cb)
        logger.info("user_events subscriber started (%s)", settings.nats_url)
        return SubscriberHandle(connection=nc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("user_events subscriber not started: %s", exc)
        return SubscriberHandle(connection=None)
