from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import HrSettings
from app.domain.repositories.hr_repository import HrRepository

logger = logging.getLogger("hr-service.user_events")

USER_EVENT_SUBJECTS = ("user.created", "user.updated", "user.deactivated", "user.deleted")
STREAM_NAME = "USER_EVENTS"
DURABLE = "HR_USER_LIFECYCLE"


class ProfilePublisher(Protocol):
    async def publish_profile_updated(self, payload: dict[str, Any]) -> None:
        ...


async def handle_user_event(
    subject: str,
    payload: dict,
    repo: HrRepository,
    publisher: ProfilePublisher | None = None,
    *,
    default_annual_leave: int = 12,
    default_sick_leave: int = 10,
) -> None:
    """Áp event vòng đời user vào hồ sơ HR. Idempotent (upsert + ON CONFLICT). Tách
    riêng khỏi NATS để test nhanh, không nuốt lỗi (lỗi -> raise cho caller nak/retry)."""
    user_id = str(payload["user_id"]).strip()
    if not user_id:
        raise ValueError("user event missing user_id")

    if subject == "user.deleted":
        # Hard delete: xoá hồ sơ employee + dữ liệu HR theo user_id. Idempotent
        # (thiếu hàng = no-op). Không upsert, không publish profile.
        await repo.delete_employee_by_user_id(user_id)
        return

    email = str(payload.get("email", ""))
    department = str(payload.get("department", ""))
    account_type = str(payload.get("account_type", "internal") or "internal")
    is_active = bool(payload.get("is_active", subject != "user.deactivated"))
    employment_status = "active" if is_active else "inactive"

    await repo.upsert_employee_from_user(user_id, email, department, is_active, account_type)
    if is_active:
        # User đang hoạt động -> đảm bảo có hồ sơ phép với hạn mức mặc định từ config.
        await repo.ensure_leave_balance(user_id, default_annual_leave, default_sick_leave)
    if publisher is not None:
        try:
            await publisher.publish_profile_updated(
                {
                    "user_id": user_id,
                    "account_type": account_type,
                    "department": department,
                    "employment_status": employment_status,
                }
            )
        except Exception:
            logger.warning(
                "failed to publish hr.employee_profile.updated for user_id=%s",
                user_id,
                exc_info=True,
            )


async def _ensure_user_events_stream(js) -> None:
    """Đảm bảo stream USER_EVENTS chứa đủ USER_EVENT_SUBJECTS.

    Stream có thể được tạo trước khi có subject mới (vd user.deleted thêm sau).
    Nếu thiếu: update_stream để bổ sung. Best-effort: lỗi chỉ log warning.
    """
    wanted = set(USER_EVENT_SUBJECTS)
    try:
        info = await js.stream_info(STREAM_NAME)
        current = set(getattr(getattr(info, "config", None), "subjects", None) or [])
        if not wanted.issubset(current):
            try:
                from nats.js.api import StreamConfig  # noqa: PLC0415

                merged = sorted(current | wanted)
                await js.update_stream(StreamConfig(name=STREAM_NAME, subjects=merged))
                logger.info("updated NATS stream %s subjects -> %s", STREAM_NAME, merged)
            except Exception as exc:  # noqa: BLE001
                logger.warning("failed to update NATS stream %s subjects: %s", STREAM_NAME, exc)
    except Exception:
        # Stream chưa tồn tại: User Service sẽ tạo khi publish lần đầu.
        # Subscribe sẽ lỗi per-subject và được log riêng — không crash toàn bộ.
        try:
            await js.add_stream(name=STREAM_NAME, subjects=sorted(wanted))
            logger.info("created NATS stream %s", STREAM_NAME)
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to create NATS stream %s: %s", STREAM_NAME, exc)


@dataclass
class SubscriberHandle:
    connection: object | None

    async def close(self) -> None:
        if self.connection is not None:
            await self.connection.drain()


async def start_user_events_subscriber(
    settings: HrSettings,
    repo_factory,
    publisher: ProfilePublisher | None = None,
    *,
    nats_module=None,
) -> SubscriberHandle:
    """Best-effort: lỗi kết nối CHỈ log warning + trả handle rỗng, KHÔNG crash service.
    Sync vẫn được lưới an toàn bởi hr lazy auto-create."""
    if not settings.user_events_enabled:
        logger.info("user_events subscriber disabled")
        return SubscriberHandle(connection=None)
    try:
        nats = nats_module or __import__("nats")
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
                    await handle_user_event(
                        message.subject,
                        payload,
                        repo,
                        publisher,
                        default_annual_leave=settings.default_annual_leave,
                        default_sick_leave=settings.default_sick_leave,
                    )
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
            await _ensure_user_events_stream(js)
            for subject in USER_EVENT_SUBJECTS:
                try:
                    await js.subscribe(subject, durable=f"{DURABLE}_{subject.replace('.', '_')}", cb=_cb)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("failed to subscribe user event subject %s: %s", subject, exc)
        else:
            for subject in USER_EVENT_SUBJECTS:
                await nc.subscribe(subject, cb=_cb)
        logger.info("user_events subscriber started (%s)", settings.nats_url)
        return SubscriberHandle(connection=nc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("user_events subscriber not started: %s", exc)
        return SubscriberHandle(connection=None)
