"""NatsBroker — wrapper mỏng quanh NATS JetStream cho rag-worker.

Ingest đi qua NATS: BE publish `doc.ingest` -> rag-worker subscribe (durable
consumer) -> enqueue job -> publish `doc.status`. Đây chỉ là lớp hạ tầng (kết nối,
ensure stream, subscribe, publish); việc map payload/ack nằm ở interfaces/nats.

`nats-py` được import LAZY trong `connect()` -> service vẫn boot/test được khi
chưa cài lib (giống boto3 ở s3_parser). Không set NATS_URL -> không đụng tới NATS.
"""

from __future__ import annotations

import asyncio
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
        """Tạo stream nếu chưa có; nếu đã có mà THIẾU subject thì cập nhật (idempotent).

        add_stream chỉ chạy lần đầu. Khi thêm subject mới (vd doc.access)
        vào một stream đã tồn tại, phải update_stream — nếu không subject mới KHÔNG
        được stream bắt và durable subscribe sẽ lỗi. Lỗi connection/permission ở
        stream_info được propagate (không nuốt thành 'tạo mới')."""
        from nats.js.api import StreamConfig
        from nats.js.errors import NotFoundError

        try:
            info = await self._js.stream_info(stream)
        except NotFoundError:
            await self._js.add_stream(StreamConfig(name=stream, subjects=subjects))
            return

        existing = list(getattr(info.config, "subjects", None) or [])
        missing = [s for s in subjects if s not in existing]
        if missing:
            info.config.subjects = existing + missing
            await self._js.update_stream(info.config)

    async def verify_stream(self, stream: str, subjects: list[str]) -> None:
        """Verify-only (fail-closed): KHÔNG tạo/sửa stream.

        Stream là hợp đồng hạ tầng do DevOps provision trước khi service lên
        (xem infra/nats/jetstream.conf). rag-worker chỉ là consumer/publisher —
        nó kiểm tra stream đã tồn tại + phủ đủ subject rồi mới subscribe. Thiếu ->
        raise để caller degrade gracefully + log ERROR, thay vì tự `add_stream` ra
        một stream lệch tên/lệch retention so với contract.

        Dev/CI muốn rag-worker tự dựng stream: đặt NATS_STREAM_AUTO_CREATE=1
        (runtime sẽ gọi ensure_stream thay vì verify_stream)."""
        from nats.js.errors import NotFoundError

        try:
            info = await self._js.stream_info(stream)
        except NotFoundError as exc:
            raise RuntimeError(
                f"JetStream stream {stream!r} chưa tồn tại. DevOps phải tạo trước khi "
                "rag-worker start (xem infra/nats/jetstream.conf). Dev/CI: đặt "
                "NATS_STREAM_AUTO_CREATE=1 để rag-worker tự dựng."
            ) from exc

        existing = list(getattr(info.config, "subjects", None) or [])
        missing = [s for s in subjects if s not in existing]
        if missing:
            raise RuntimeError(
                f"JetStream stream {stream!r} thiếu subject {missing} (hiện có "
                f"{existing}). DevOps cập nhật stream theo infra/nats/jetstream.conf."
            )

    async def subscribe(
        self,
        subject: str,
        *,
        durable: str,
        cb: MessageHandler,
    ) -> Any:
        """Durable push-subscribe; ack thủ công (cb tự ack/nak).

        Một subscription/process (worker poll DB queue, không poll NATS). Multi-replica
        cần deliver-group/pull consumer — TODO khi scale ngang (xem docs/ops/ingest-transport.md).

        Retry "already bound": durable push-consumer chỉ 1 subscriber active. Khi deploy restart,
        binding của instance cũ chưa release ngay -> instance mới raise "consumer already bound".
        TRƯỚC: raise luôn -> subscription chết, không ai retry (doc.access delete-cascade dừng hẳn).
        NAY: retry vài nhịp chờ binding cũ nhả -> 1 instance bám lại được. Lỗi khác -> raise ngay.
        """
        last_exc: Exception | None = None
        for attempt in range(5):
            try:
                return await self._js.subscribe(
                    subject,
                    durable=durable,
                    cb=cb,
                    manual_ack=True,
                )
            except Exception as exc:  # noqa: BLE001 - chỉ nuốt "already bound", còn lại raise
                if "already bound" not in str(exc).lower():
                    raise
                last_exc = exc
                self._logger.warning(
                    "nats_subscribe_already_bound subject=%s durable=%s attempt=%d/5",
                    subject, durable, attempt + 1,
                )
                await asyncio.sleep(2.0)
        assert last_exc is not None
        raise last_exc

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
