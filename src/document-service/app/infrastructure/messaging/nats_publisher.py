import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

from app.core.config import Settings


JETSTREAM_EVENT_SUBJECTS = {"doc.ingest", "doc.access", "doc.status", "notify.doc_new"}


class NatsPublisher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._connection = None
        self._connect_lock = asyncio.Lock()

    async def publish_doc_ingest(self, payload: dict) -> None:
        await self._publish("doc.ingest", payload)

    async def publish_doc_access(self, payload: dict) -> None:
        await self._publish("doc.access", payload)

    async def publish_notify_doc_new(self, payload: dict) -> None:
        await self._publish("notify.doc_new", payload)

    async def health_check(self) -> bool:
        try:
            nc = await self._get_connection()
            return nc.is_connected
        except Exception:
            return False

    async def _publish(self, subject: str, payload: dict) -> None:
        nc = await self._get_connection()
        data = json.dumps(_with_event_metadata(subject, payload)).encode("utf-8")
        if self.settings.nats_jetstream_enabled:
            js = nc.jetstream()
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


def _with_event_metadata(subject: str, payload: dict) -> dict:
    if subject not in JETSTREAM_EVENT_SUBJECTS:
        return payload
    enriched = dict(payload)
    enriched.setdefault("event_id", str(uuid4()))
    enriched.setdefault("event_version", 1)
    enriched.setdefault(
        "occurred_at",
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )
    return enriched

