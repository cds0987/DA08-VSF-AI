"""interfaces/nats - ingest entrypoints over NATS JetStream.

Flow:
    BE publish doc.ingest  ->  DocIngestConsumer.handle: map payload -> enqueue job
                           ->  ack (message is durable in DB queue + lease/retry)
    worker DB finishes     ->  DocStatusPublisher.publish_for_job -> publish doc.status

Consumer/publisher do not depend on the NATS SDK directly. They only operate on
bytes / dict plus a broker with `publish_json`, so unit tests can run with fakes.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.application.use_cases.ingestion import IngestDocumentUseCase
from app.domain.entities.ingest_job import IngestJob, IngestJobStatus
from app.infrastructure.external.s3_parser import S3_SOURCE_URI_SCHEMES

MAX_DOCUMENT_ID_LENGTH = 255
MAX_DOCUMENT_NAME_LENGTH = 512


class BadPayloadError(ValueError):
    """Poison payload for doc.ingest/doc.access that should be terminated."""


def normalize_source_uri(key: str, *, default_bucket: str | None) -> str:
    """Normalize an object key into the source URI expected by the parser."""
    if key.startswith(S3_SOURCE_URI_SCHEMES):
        return key
    if default_bucket:
        return f"s3://{default_bucket.strip('/')}/{key.lstrip('/')}"
    return key


class DocIngestConsumer:
    """Map payload `doc.ingest` -> enqueue ingest job. Returns document_id."""

    def __init__(
        self,
        ingest_use_case: IngestDocumentUseCase,
        *,
        default_bucket: str | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._ingest = ingest_use_case
        self._default_bucket = default_bucket
        self._logger = logger or logging.getLogger(__name__)

    async def handle(self, raw: bytes) -> str:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BadPayloadError(f"doc.ingest payload is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise BadPayloadError("doc.ingest payload must be a JSON object")

        doc_id = str(payload.get("doc_id") or "").strip()
        gcs_key = str(payload.get("gcs_key") or payload.get("s3_key") or "").strip()
        file_type = str(payload.get("file_type") or "").strip()
        document_name = str(payload.get("document_name") or doc_id).strip() or doc_id
        if not doc_id or not gcs_key or not file_type:
            raise BadPayloadError(
                "doc.ingest requires doc_id, gcs_key (or s3_key), and file_type"
            )
        if len(doc_id) > MAX_DOCUMENT_ID_LENGTH:
            raise BadPayloadError(
                f"doc.ingest doc_id exceeds max length {MAX_DOCUMENT_ID_LENGTH}"
            )
        if len(document_name) > MAX_DOCUMENT_NAME_LENGTH:
            self._logger.warning(
                "doc_ingest_document_name_truncated doc_id=%s original_length=%s max_length=%s",
                doc_id,
                len(document_name),
                MAX_DOCUMENT_NAME_LENGTH,
            )
            document_name = document_name[:MAX_DOCUMENT_NAME_LENGTH]

        source_uri = normalize_source_uri(gcs_key, default_bucket=self._default_bucket)
        await self._ingest.enqueue(
            document_id=doc_id,
            document_name=document_name,
            file_type=file_type,
            markdown=None,
            source_uri=source_uri,
            correlation_id=f"nats:doc.ingest:{doc_id}",
        )
        return doc_id


class DocAccessDeleteConsumer:
    """Map payload `doc.access` with `deleted=true` -> delete vectors + metadata."""

    def __init__(
        self,
        ingest_use_case: IngestDocumentUseCase,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._ingest = ingest_use_case
        self._logger = logger or logging.getLogger(__name__)

    async def handle(self, raw: bytes) -> str | None:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BadPayloadError(f"doc.access payload is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise BadPayloadError("doc.access payload must be a JSON object")

        if not bool(payload.get("deleted")):
            return None

        doc_id = str(payload.get("doc_id") or "").strip()
        if not doc_id:
            raise BadPayloadError("doc.access deleted event requires doc_id")

        await self._ingest.delete(doc_id)
        return doc_id


def build_doc_status(job: IngestJob) -> dict | None:
    """Map a terminal job to doc.status payload."""
    if job.status == IngestJobStatus.COMPLETED:
        return {
            "doc_id": job.document_id,
            "status": "indexed",
            "chunk_count": job.chunk_count,
        }
    if job.status == IngestJobStatus.FAILED:
        return {
            "doc_id": job.document_id,
            "status": "failed",
            "error": job.error_message or "",
        }
    return None


class DocStatusPublisher:
    """Publish doc.status after the DB worker processes a job."""

    def __init__(
        self,
        broker: Any,
        *,
        subject: str,
        logger: logging.Logger | None = None,
    ) -> None:
        self._broker = broker
        self._subject = subject
        self._logger = logger or logging.getLogger(__name__)

    async def publish_for_job(self, job: IngestJob) -> None:
        message = build_doc_status(job)
        if message is None:
            return
        try:
            await self._broker.publish_json(self._subject, message)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning(
                "doc_status_publish_failed doc_id=%s error=%s",
                job.document_id,
                exc,
            )


async def start_doc_ingest_subscription(
    broker: Any,
    consumer: DocIngestConsumer,
    *,
    subject: str,
    durable: str,
    logger: logging.Logger | None = None,
) -> Any:
    """Subscribe to doc.ingest; ack on success, term poison payload, nak transient errors."""
    log = logger or logging.getLogger(__name__)

    async def _cb(msg: Any) -> None:
        try:
            doc_id = await consumer.handle(msg.data)
            await msg.ack()
            log.info("doc_ingest_enqueued doc_id=%s", doc_id)
        except BadPayloadError as exc:
            log.warning("doc_ingest_bad_payload error=%s", exc)
            term = getattr(msg, "term", None)
            if callable(term):
                await term()
            else:  # pragma: no cover
                await msg.ack()
        except Exception as exc:  # noqa: BLE001
            log.warning("doc_ingest_enqueue_failed error=%s", exc)
            await msg.nak()

    return await broker.subscribe(subject, durable=durable, cb=_cb)


async def start_doc_access_subscription(
    broker: Any,
    consumer: DocAccessDeleteConsumer,
    *,
    subject: str,
    durable: str,
    logger: logging.Logger | None = None,
) -> Any:
    """Subscribe to doc.access; delete when deleted=true, ack or skip other events."""
    log = logger or logging.getLogger(__name__)

    async def _cb(msg: Any) -> None:
        try:
            doc_id = await consumer.handle(msg.data)
            await msg.ack()
            if doc_id:
                log.info("doc_access_delete_done doc_id=%s", doc_id)
        except BadPayloadError as exc:
            log.warning("doc_access_bad_payload error=%s", exc)
            term = getattr(msg, "term", None)
            if callable(term):
                await term()
            else:  # pragma: no cover
                await msg.ack()
        except Exception as exc:  # noqa: BLE001
            log.warning("doc_access_delete_failed error=%s", exc)
            await msg.nak()

    return await broker.subscribe(subject, durable=durable, cb=_cb)
