"""NatsBroker — wrapper mỏng quanh NATS JetStream cho rag-worker.

Ingest đi qua NATS: BE publish `doc.ingest` -> rag-worker subscribe (durable
consumer) -> enqueue job -> publish `doc.status`. Đây chỉ là lớp hạ tầng (kết nối,
ensure stream, subscribe, publish); việc map payload/ack nằm ở interfaces/nats.

`nats-py` được import LAZY trong `connect()` -> service vẫn boot/test được khi
chưa cài lib (giống boto3 ở s3_parser). Không set NATS_URL -> không đụng tới NATS.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

MessageHandler = Callable[[Any], Awaitable[None]]


class NatsBroker:
    def __init__(self, url: str, *, name: str = "rag-worker") -> None:
        self._url = url
        self._name = name
        self._nc: Any = None
        self._js: Any = None
        self._logger = logging.getLogger(__name__)

    async def connect(self) -> "NatsBroker":
        try:
            import nats  # lazy: chưa cài nats-py thì service vẫn boot
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise ModuleNotFoundError(
                "NATS ingest cần nats-py. Cài: pip install nats-py"
            ) from exc
        self._nc = await nats.connect(self._url, name=self._name)
        self._js = self._nc.jetstream()
        return self

    async def ensure_stream(self, stream: str, subjects: list[str]) -> None:
        """Tạo stream nếu chưa có (idempotent). Bỏ qua nếu đã tồn tại."""
        from nats.js.api import StreamConfig

        try:
            await self._js.stream_info(stream)
        except Exception:  # noqa: BLE001 - stream chưa tồn tại -> tạo mới
            await self._js.add_stream(StreamConfig(name=stream, subjects=subjects))

    async def subscribe(
        self,
        subject: str,
        *,
        durable: str,
        queue: str,
        cb: MessageHandler,
    ) -> Any:
        """Push-subscribe durable + queue group; ack thủ công (cb tự ack/nak)."""
        return await self._js.subscribe(
            subject,
            durable=durable,
            queue=queue,
            cb=cb,
            manual_ack=True,
        )

    async def publish_json(self, subject: str, payload: dict) -> None:
        await self._js.publish(subject, json.dumps(payload).encode("utf-8"))

    async def close(self) -> None:
        if self._nc is not None:
            try:
                await self._nc.drain()
            except Exception as exc:  # noqa: BLE001 - shutdown best-effort
                self._logger.warning("nats_drain_failed: %s", exc)
            self._nc = None
            self._js = None
