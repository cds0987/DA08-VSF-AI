from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.config import HrSettings

logger = logging.getLogger(__name__)

# Leave Write events (best-effort, publish SAU commit). JetStream lưu bền -> consumer
# (query-service Notification Center) tắt tạm thời cũng không mất thông báo.
LEAVE_REQUEST_SUBJECTS = [
    "hr.leave_request.created",
    "hr.leave_request.updated",
    "hr.leave_request.cancelled",
    "hr.leave_request.approved",
    "hr.leave_request.rejected",
]
HR_EVENT_SUBJECTS = {"hr.employee_profile.updated", *LEAVE_REQUEST_SUBJECTS}
JETSTREAM_STREAMS = {"HR_EVENTS": ["hr.employee_profile.updated", *LEAVE_REQUEST_SUBJECTS]}


@dataclass
class NatsPublisher:
    settings: HrSettings
    _connection: Any = None
    _connect_lock: asyncio.Lock | None = None

    def __post_init__(self) -> None:
        self._connect_lock = asyncio.Lock()

    async def publish_profile_updated(self, payload: dict[str, Any]) -> None:
        await self.publish("hr.employee_profile.updated", payload)

    async def publish(self, subject: str, payload: dict[str, Any]) -> None:
        nc = await self._get_connection()
        data = json.dumps(_with_event_metadata(subject, payload)).encode("utf-8")
        if self.settings.nats_jetstream_enabled:
            js = nc.jetstream()
            await ensure_jetstream_streams(js)
            await js.publish(subject, data)
        else:
            await nc.publish(subject, data)
            await nc.flush()

    async def aclose(self) -> None:
        if self._connection is not None:
            await self._connection.drain()
            self._connection = None

    async def _get_connection(self):
        if self._connection is not None and self._connection.is_connected:
            return self._connection
        assert self._connect_lock is not None
        async with self._connect_lock:
            if self._connection is not None and self._connection.is_connected:
                return self._connection
            nats = _import_nats()
            self._connection = await nats.connect(self.settings.nats_url)
            return self._connection


def _import_nats():
    try:
        import nats
    except ImportError as exc:
        raise RuntimeError("nats-py is required for NATS messaging") from exc
    return nats


async def ensure_jetstream_streams(js) -> None:
    for name, subjects in JETSTREAM_STREAMS.items():
        try:
            info = await js.stream_info(name)
        except Exception:
            # Chưa có stream -> tạo mới đủ subject. Lỗi tạo -> raise (publish best-effort
            # ở route sẽ nuốt) để không âm thầm publish vào hư không.
            try:
                await js.add_stream(name=name, subjects=subjects)
            except Exception as exc:
                logger.warning("failed to ensure NATS stream %s: %s", name, exc)
                raise
            continue
        # Stream đã tồn tại (vd HR_EVENTS cũ chỉ có hr.employee_profile.updated): bổ
        # sung subject còn THIẾU (hr.leave_request.*) thay vì bỏ qua. Best-effort: lỗi
        # update chỉ log (stream cũ vẫn chạy cho subject cũ), KHÔNG raise.
        try:
            current = set(getattr(getattr(info, "config", None), "subjects", None) or [])
            wanted = set(subjects)
            if not wanted.issubset(current):
                from nats.js.api import StreamConfig

                merged = sorted(current | wanted)
                await js.update_stream(StreamConfig(name=name, subjects=merged))
                logger.info("updated NATS stream %s subjects -> %s", name, merged)
        except Exception as exc:  # noqa: BLE001 — best-effort update
            logger.warning("failed to update NATS stream %s subjects: %s", name, exc)


def _with_event_metadata(subject: str, payload: dict[str, Any]) -> dict[str, Any]:
    if subject not in HR_EVENT_SUBJECTS:
        return dict(payload)
    enriched = dict(payload)
    enriched.setdefault("event_id", str(uuid4()))
    enriched.setdefault("event_version", 1)
    enriched.setdefault(
        "occurred_at",
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )
    return enriched
