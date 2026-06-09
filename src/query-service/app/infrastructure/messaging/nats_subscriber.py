import json
import logging
from typing import Any

from app.infrastructure.messaging.nats_events import (
    InvalidNatsEventPayload,
    QueryNatsEventHandler,
    parse_doc_access_event,
    parse_hr_employee_profile_updated_event,
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

    async def start(self) -> None:
        if self._connection is not None:
            return
        nats_module = self._nats_module or _import_nats()
        self._connection = await nats_module.connect(self._settings.nats_url)
        jetstream = self._connection.jetstream()
        await jetstream.subscribe(
            "doc.access",
            durable="QUERY_SERVICE_DOC_ACCESS",
            cb=self._doc_access_callback,
        )
        await jetstream.subscribe(
            "notify.doc_new",
            durable="QUERY_SERVICE_NOTIFY_DOC_NEW",
            cb=self._notify_doc_new_callback,
        )
        await jetstream.subscribe(
            "hr.employee_profile.updated",
            durable="QUERY_SERVICE_HR_PROFILE",
            cb=self._hr_employee_profile_callback,
        )

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
        except Exception as exc:  # noqa: BLE001 - retry transient repository/SSE failures
            self._logger.warning("nats_event_processing_failed error=%s", exc)
            nak = getattr(msg, "nak", None)
            if callable(nak):
                await nak()
            else:
                raise


def _import_nats():
    try:
        import nats
    except ImportError as exc:
        raise RuntimeError("nats-py is required for NATS subscriber mode") from exc
    return nats
