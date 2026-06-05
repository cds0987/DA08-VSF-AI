import asyncio
import json
import logging
from dataclasses import dataclass

from app.core.config import Settings
from app.domain.entities.document import DocumentStatus
from app.infrastructure.db.postgres_document_repository import PostgresDocumentRepository
from app.infrastructure.db.session import AsyncSessionLocal
from app.infrastructure.messaging.nats_publisher import NatsPublisher


logger = logging.getLogger(__name__)


@dataclass
class SubscriberHandle:
    connection: object | None
    task: asyncio.Task | None = None

    async def close(self) -> None:
        if self.task is not None:
            self.task.cancel()
        if self.connection is not None:
            await self.connection.drain()


async def start_status_subscriber(settings: Settings) -> SubscriberHandle:
    try:
        import nats
    except ImportError:
        logger.warning("nats-py is not installed; doc.status subscriber not started")
        return SubscriberHandle(connection=None)

    try:
        nc = await nats.connect(settings.nats_url)
        publisher = NatsPublisher(settings)

        async def handle_message(message) -> None:
            await _handle_status_message(message, publisher)

        if settings.nats_jetstream_enabled:
            js = nc.jetstream()
            await js.subscribe(
                "doc.status",
                durable="document-service-status",
                cb=handle_message,
            )
        else:
            await nc.subscribe("doc.status", cb=handle_message)
        return SubscriberHandle(connection=nc)
    except Exception as exc:
        logger.warning("doc.status subscriber not started: %s", exc)
        return SubscriberHandle(connection=None)


async def _handle_status_message(message, publisher: NatsPublisher) -> None:
    try:
        payload = json.loads(message.data.decode("utf-8"))
        status = DocumentStatus(str(payload["status"]))
        if status not in {DocumentStatus.INDEXED, DocumentStatus.FAILED}:
            raise ValueError("doc.status only accepts indexed or failed")
        doc_id = str(payload["doc_id"])
        chunk_count = int(payload.get("chunk_count") or 0)
        error = payload.get("error")

        async with AsyncSessionLocal() as session:
            repo = PostgresDocumentRepository(session)
            await repo.update_status(doc_id, status, chunk_count=chunk_count, error=error)
            document = await repo.get_by_id(doc_id)

        if status == DocumentStatus.INDEXED and document is not None:
            await publisher.publish_notify_doc_new(
                {
                    "doc_id": document.id,
                    "document_name": document.name,
                    "classification": document.classification,
                    "allowed_departments": document.allowed_departments,
                    "allowed_user_ids": document.allowed_user_ids,
                },
            )
        if hasattr(message, "ack"):
            await message.ack()
    except Exception:
        logger.exception("failed to handle doc.status message")
        if hasattr(message, "nak"):
            await message.nak()

