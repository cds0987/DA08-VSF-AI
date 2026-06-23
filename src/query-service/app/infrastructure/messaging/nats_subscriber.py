import json
import logging
from typing import Any

from app.infrastructure.messaging.nats_events import (
    InvalidNatsEventPayload,
    QueryNatsEventHandler,
    parse_doc_access_event,
    parse_hr_employee_profile_updated_event,
    parse_leave_request_status_event,
    parse_notify_doc_new_event,
)


class NatsSubscriberManager:
    def __init__(
        self,
        settings,
        handler: QueryNatsEventHandler,
        *,
        nats_module=None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._settings = settings
        self._handler = handler
        self._nats_module = nats_module
        self._logger = logger or logging.getLogger(__name__)
        self._connection = None

    # (subject, durable, tên-stream-fallback, callback). Stream-fallback chỉ dùng khi
    # CHƯA có stream nào phủ subject (vd hr.employee_profile.updated — hr-service hiện
    # publish no-op nên không ai tạo stream). doc.access/notify.doc_new đã có stream sẵn.
    _SUBSCRIPTIONS = (
        ("doc.access", "QUERY_SERVICE_DOC_ACCESS", "QUERY_DOC_ACCESS"),
        ("notify.doc_new", "QUERY_SERVICE_NOTIFY_DOC_NEW", "QUERY_NOTIFY_DOC_NEW"),
        ("hr.employee_profile.updated", "QUERY_SERVICE_HR_PROFILE", "QUERY_HR_PROFILE"),
        ("hr.leave_request.approved", "QUERY_SERVICE_LEAVE_APPROVED", "HR_EVENTS"),
        ("hr.leave_request.rejected", "QUERY_SERVICE_LEAVE_REJECTED", "HR_EVENTS"),
    )

    async def start(self) -> None:
        if self._connection is not None:
            return
        nats_module = self._nats_module or _import_nats()
        self._connection = await nats_module.connect(self._settings.nats_url)
        jetstream = self._connection.jetstream()
        callbacks = {
            "doc.access": self._doc_access_callback,
            "notify.doc_new": self._notify_doc_new_callback,
            "hr.employee_profile.updated": self._hr_employee_profile_callback,
            "hr.leave_request.approved": self._leave_request_status_callback,
            "hr.leave_request.rejected": self._leave_request_status_callback,
        }
        # Resilient: lỗi 1 subscription (stream chưa sẵn) KHÔNG được làm chết startup —
        # query-service vẫn phải phục vụ HTTP (chat/query/dashboard).
        for subject, durable, stream_name in self._SUBSCRIPTIONS:
            try:
                await self._ensure_subject_stream(jetstream, subject, stream_name)
                await self._subscribe(jetstream, subject, durable, callbacks[subject])
            except Exception as exc:  # noqa: BLE001 - degrade gracefully thay vì crash
                self._logger.warning(
                    "nats_subscribe_skipped subject=%s error=%s", subject, exc,
                )

    async def _subscribe(self, jetstream, subject: str, durable: str, cb) -> None:
        """Subscribe có CHẶN redeliver vô hạn: max_deliver + backoff lũy tiến.

        Backstop cho poison-message (lỗi vĩnh viễn) — cùng tầng với phân loại lỗi ở
        _handle_message. Sự cố 2026-06-16: nak() vô hạn + không backoff -> NAK-storm
        hàng trăm/giây -> query-service nghẽn. FALLBACK: nếu phiên bản nats-py không nhận
        ConsumerConfig này, subscribe trần — TUYỆT ĐỐI không để mất subscription."""
        try:
            from nats.js.api import ConsumerConfig

            cfg = ConsumerConfig(
                max_deliver=6,                  # quá 6 lần -> NATS ngừng giao (không lặp vô tận)
                ack_wait=30,                    # giây
                backoff=[1, 5, 15, 30, 60],     # giãn cách giữa các lần retry (giây)
            )
            await jetstream.subscribe(subject, durable=durable, cb=cb, config=cfg)
        except Exception as exc:  # noqa: BLE001 - config không hợp lệ KHÔNG được mất subscription
            self._logger.warning(
                "nats_subscribe_policy_fallback subject=%s error=%s", subject, exc,
            )
            await jetstream.subscribe(subject, durable=durable, cb=cb)

    async def _ensure_subject_stream(self, jetstream, subject: str, stream_name: str) -> None:
        """Tạo stream cho subject nếu CHƯA có stream nào phủ nó (idempotent, không đụng
        stream sẵn của subject khác)."""
        from nats.js.api import StreamConfig
        from nats.js.errors import NotFoundError

        try:
            await jetstream.find_stream_name_by_subject(subject)
            return  # đã có stream phủ subject này
        except NotFoundError:
            pass
        try:
            await jetstream.add_stream(StreamConfig(name=stream_name, subjects=[subject]))
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("nats_ensure_stream_failed subject=%s error=%s", subject, exc)

    async def stop(self) -> None:
        if self._connection is not None:
            await self._connection.drain()
            self._connection = None

    async def _doc_access_callback(self, msg: Any) -> None:
        await self._handle_message(
            msg,
            validate=parse_doc_access_event,
            handle=self._handler.handle_doc_access,
        )

    async def _notify_doc_new_callback(self, msg: Any) -> None:
        await self._handle_message(
            msg,
            validate=parse_notify_doc_new_event,
            handle=self._handler.handle_notify_doc_new,
        )

    async def _leave_request_status_callback(self, msg: Any) -> None:
        await self._handle_message(
            msg,
            validate=parse_leave_request_status_event,
            handle=self._handler.handle_leave_request_status,
        )

    async def _hr_employee_profile_callback(self, msg: Any) -> None:
        await self._handle_message(
            msg,
            validate=parse_hr_employee_profile_updated_event,
            handle=self._handler.handle_hr_employee_profile_updated,
        )

    async def _handle_message(self, msg: Any, *, validate, handle) -> None:
        try:
            payload = json.loads(msg.data)
            if not isinstance(payload, dict):
                raise InvalidNatsEventPayload("event payload must be a JSON object")
            validate(payload)
        except (json.JSONDecodeError, UnicodeDecodeError, InvalidNatsEventPayload) as exc:
            self._logger.warning("nats_event_bad_payload error=%s", exc)
            await msg.ack()
            return

        try:
            await handle(payload)
            await msg.ack()
        except Exception as exc:  # noqa: BLE001
            if _is_permanent_error(exc):
                # Lỗi VĨNH VIỄN (bảng/cột thiếu, syntax, data sai) — retry vô ích, chỉ tạo
                # NAK-storm (sự cố 2026-06-16). Đẩy DLQ giữ lại để xử lý tay + term() (bỏ
                # khỏi hàng đợi, KHÔNG redeliver).
                self._logger.error(
                    "nats_event_permanent_failure subject=%s error=%s -> DLQ+term",
                    getattr(msg, "subject", "?"), exc,
                )
                await self._to_dlq(msg)
                term = getattr(msg, "term", None)
                if callable(term):
                    await term()
                else:
                    await msg.ack()  # client cũ không có term() -> ack để chặn lặp vô tận
            else:
                # Lỗi TẠM THỜI (DB bận, mạng) — nak để retry; max_deliver chặn vô hạn.
                self._logger.warning("nats_event_processing_failed error=%s", exc)
                nak = getattr(msg, "nak", None)
                if callable(nak):
                    await nak()
                else:
                    raise

    async def _to_dlq(self, msg: Any) -> None:
        """Giữ message lỗi-vĩnh-viễn ở subject <subject>.dlq để xử lý tay + cảnh báo.
        KHÔNG để mất dữ liệu: chỉ chuyển chỗ, không xóa. Publish lỗi -> chỉ cảnh báo."""
        try:
            subject = getattr(msg, "subject", None)
            if subject and self._connection is not None:
                await self._connection.publish(f"{subject}.dlq", msg.data)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("nats_dlq_publish_failed error=%s", exc)


# sqlstate Postgres của lỗi VĨNH VIỄN (retry vô ích): 42=undefined table/col/syntax,
# 22=data exception, 23=integrity (sau ON CONFLICT vẫn lỗi = data sai). Lỗi TẠM THỜI
# (08 connection, 40001 serialize, 53300 too-many-conn, 55P03 lock) -> để nak retry.
_PERMANENT_SQLSTATE_PREFIXES = ("42", "22", "23")


def _is_permanent_error(exc: BaseException) -> bool:
    """True nếu lỗi không thể tự khỏi khi retry -> nên term()+DLQ thay vì nak vô hạn."""
    if isinstance(exc, InvalidNatsEventPayload):
        return True
    code = getattr(exc, "sqlstate", None)  # asyncpg.PostgresError có .sqlstate
    return bool(code) and code[:2] in _PERMANENT_SQLSTATE_PREFIXES


def _import_nats():
    try:
        import nats
    except ImportError as exc:
        raise RuntimeError("nats-py is required for NATS subscriber mode") from exc
    return nats
