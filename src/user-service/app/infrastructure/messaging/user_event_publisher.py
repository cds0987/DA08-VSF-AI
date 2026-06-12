from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

# Theo infra/nats/subjects.md — USER_EVENTS.
USER_EVENT_SUBJECTS = ("user.created", "user.updated", "user.deactivated")
JETSTREAM_STREAMS = {"USER_EVENTS": list(USER_EVENT_SUBJECTS)}


def build_user_event(user: dict[str, Any]) -> dict[str, Any]:
    """Payload chuẩn theo subjects.md (business fields top-level + metadata)."""
    return {
        "event_id": str(uuid4()),
        "event_version": 1,
        "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "user_id": str(user["user_id"]),
        "email": str(user.get("email", "")),
        "role": str(user.get("role", "")),
        "department": str(user.get("department", "")),
        "account_type": str(user.get("account_type", "internal")),
        "is_active": bool(user.get("is_active", True)),
    }


class UserEventPublisher:
    """JetStream publisher best-effort: lỗi publish KHÔNG được làm hỏng nghiệp vụ
    (tạo/đổi user). Lưới an toàn cho sync là backfill + hr lazy auto-create."""

    def __init__(self, nats_url: str, jetstream_enabled: bool = True) -> None:
        self._nats_url = nats_url
        self._jetstream_enabled = jetstream_enabled
        self._connection = None
        self._lock = asyncio.Lock()

    async def publish_user_event(self, subject: str, user: dict[str, Any]) -> None:
        if subject not in USER_EVENT_SUBJECTS:
            raise ValueError(f"unknown user event subject: {subject}")
        payload = build_user_event(user)
        data = json.dumps(payload).encode("utf-8")
        nc = await self._get_connection()
        if self._jetstream_enabled:
            js = nc.jetstream()
            await _ensure_streams(js)
            await js.publish(subject, data)
        else:
            await nc.publish(subject, data)
            await nc.flush()

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.drain()
            self._connection = None

    async def _get_connection(self):
        if self._connection is not None and self._connection.is_connected:
            return self._connection
        async with self._lock:
            if self._connection is not None and self._connection.is_connected:
                return self._connection
            import nats

            self._connection = await nats.connect(self._nats_url)
            return self._connection


async def _ensure_streams(js) -> None:
    for name, subjects in JETSTREAM_STREAMS.items():
        try:
            await js.stream_info(name)
        except Exception:
            try:
                await js.add_stream(name=name, subjects=subjects)
            except Exception as exc:  # noqa: BLE001
                logger.warning("failed to ensure NATS stream %s: %s", name, exc)
                raise
