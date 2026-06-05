import json

from app.core.config import Settings


class NatsPublisher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def publish_doc_ingest(self, payload: dict) -> None:
        await self._publish("doc.ingest", payload)

    async def publish_doc_access(self, payload: dict) -> None:
        await self._publish("doc.access", payload)

    async def publish_notify_doc_new(self, payload: dict) -> None:
        await self._publish("notify.doc_new", payload)

    async def health_check(self) -> bool:
        nc = None
        try:
            nats = _import_nats()
            nc = await nats.connect(self.settings.nats_url)
            return nc.is_connected
        except Exception:
            return False
        finally:
            if nc is not None:
                await nc.drain()

    async def _publish(self, subject: str, payload: dict) -> None:
        nats = _import_nats()
        nc = await nats.connect(self.settings.nats_url)
        try:
            data = json.dumps(payload).encode("utf-8")
            if self.settings.nats_jetstream_enabled:
                js = nc.jetstream()
                await js.publish(subject, data)
            else:
                await nc.publish(subject, data)
                await nc.flush()
        finally:
            await nc.drain()


def _import_nats():
    try:
        import nats
    except ImportError as exc:
        raise RuntimeError("nats-py is required for NATS messaging") from exc
    return nats

