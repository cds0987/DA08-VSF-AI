"""interfaces/nats — cửa vào ingest qua NATS JetStream (thay HTTP /ingest).

Luồng (Cách A — tái dùng job-queue DB sẵn có):
    BE publish doc.ingest  ->  DocIngestConsumer.handle: map payload -> enqueue job
                           ->  ack (message đã an toàn trong DB queue + lease/retry)
    worker DB xử lý xong   ->  DocStatusPublisher.publish_for_job -> publish doc.status

Consumer/publisher KHÔNG biết NATS SDK — chỉ nhận bytes / dict + một broker có
`publish_json`. Vì vậy unit-test được bằng broker giả, không cần NATS server.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.application.use_cases.ingestion import IngestDocumentUseCase
from app.domain.entities.ingest_job import IngestJob, IngestJobStatus


class BadPayloadError(ValueError):
    """Payload doc.ingest hỏng/thiếu field — POISON: term (không redeliver vô hạn).

    Tách riêng khỏi ValueError chung để semantics retry của transport (term vs nak)
    KHÔNG dính vào exception domain (vd enqueue raise ValueError) — lỗi domain phải
    nak để retry, chỉ payload hỏng mới term.
    """


class DocIngestConsumer:
    """Map payload `doc.ingest` -> enqueue ingest job. Trả document_id đã nhận."""

    def __init__(
        self,
        ingest_use_case: IngestDocumentUseCase,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._ingest = ingest_use_case
        self._logger = logger or logging.getLogger(__name__)

    async def handle(self, raw: bytes) -> str:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BadPayloadError(f"doc.ingest payload không phải JSON hợp lệ: {exc}") from exc
        if not isinstance(payload, dict):
            raise BadPayloadError("doc.ingest payload phải là object JSON")

        doc_id = str(payload.get("doc_id") or "").strip()
        # Chuẩn contract = gcs_key; chấp nhận s3_key để không gãy khi BE chưa đổi xong
        # (document-service hiện publish s3_key — xem docs/sync-doc-ingest-rag-worker.md §2.1).
        gcs_key = str(payload.get("gcs_key") or payload.get("s3_key") or "").strip()
        file_type = str(payload.get("file_type") or "").strip()
        if not doc_id or not gcs_key or not file_type:
            raise BadPayloadError(
                "doc.ingest thiếu trường bắt buộc: cần doc_id, gcs_key (hoặc s3_key), file_type"
            )

        # gcs_key = địa chỉ object (vd s3://bucket/key hoặc gs://bucket/key) -> source_uri.
        # PARSER_IMPL=s3 sẽ tự tải an toàn. classification/ACL là metadata thụ động,
        # rag-worker KHÔNG enforce (caller tầng trên tự lọc) -> hiện bỏ qua.
        await self._ingest.enqueue(
            document_id=doc_id,
            document_name=str(payload.get("document_name") or doc_id),
            file_type=file_type,
            markdown=None,
            source_uri=gcs_key,
            correlation_id=f"nats:doc.ingest:{doc_id}",
        )
        return doc_id


class DocDeleteConsumer:
    """Map payload `doc.delete` -> xóa vector + metadata của document. Trả document_id.

    Tái dùng `IngestDocumentUseCase.delete()` (vectors.delete_by_document + documents.delete)
    nên idempotent: xóa lại document đã xóa không phát sinh lỗi (vector store no-op).
    """

    def __init__(
        self,
        ingest_use_case: IngestDocumentUseCase,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._ingest = ingest_use_case
        self._logger = logger or logging.getLogger(__name__)

    async def handle(self, raw: bytes) -> str:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BadPayloadError(f"doc.delete payload không phải JSON hợp lệ: {exc}") from exc
        if not isinstance(payload, dict):
            raise BadPayloadError("doc.delete payload phải là object JSON")

        doc_id = str(payload.get("doc_id") or "").strip()
        if not doc_id:
            raise BadPayloadError("doc.delete thiếu trường bắt buộc: cần doc_id")

        await self._ingest.delete(doc_id)
        return doc_id


def build_doc_status(job: IngestJob) -> dict | None:
    """Map job (terminal) -> payload doc.status. Job chưa terminal -> None (ko publish)."""
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
    """Publish doc.status sau khi worker DB xử lý xong một job."""

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
        except Exception as exc:  # noqa: BLE001 - publish status ko được làm sập worker
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
    """Subscribe doc.ingest; ack khi enqueue thành công, nak để JetStream gửi lại khi lỗi."""
    log = logger or logging.getLogger(__name__)

    async def _cb(msg: Any) -> None:
        try:
            doc_id = await consumer.handle(msg.data)
            await msg.ack()
            log.info("doc_ingest_enqueued doc_id=%s", doc_id)
        except BadPayloadError as exc:
            # Payload hỏng (poison): term để KHÔNG gửi lại vô hạn.
            log.warning("doc_ingest_bad_payload error=%s", exc)
            term = getattr(msg, "term", None)
            if callable(term):
                await term()
            else:  # pragma: no cover - fallback nếu client ko có term()
                await msg.ack()
        except Exception as exc:  # noqa: BLE001 - lỗi tạm (DB...) -> nak để retry
            log.warning("doc_ingest_enqueue_failed error=%s", exc)
            await msg.nak()

    return await broker.subscribe(subject, durable=durable, cb=_cb)


async def start_doc_delete_subscription(
    broker: Any,
    consumer: DocDeleteConsumer,
    *,
    subject: str,
    durable: str,
    logger: logging.Logger | None = None,
) -> Any:
    """Subscribe doc.delete; ack khi xóa xong, term payload hỏng, nak lỗi tạm để retry."""
    log = logger or logging.getLogger(__name__)

    async def _cb(msg: Any) -> None:
        try:
            doc_id = await consumer.handle(msg.data)
            await msg.ack()
            log.info("doc_delete_done doc_id=%s", doc_id)
        except BadPayloadError as exc:
            # Payload hỏng (poison): term để KHÔNG gửi lại vô hạn.
            log.warning("doc_delete_bad_payload error=%s", exc)
            term = getattr(msg, "term", None)
            if callable(term):
                await term()
            else:  # pragma: no cover - fallback nếu client ko có term()
                await msg.ack()
        except Exception as exc:  # noqa: BLE001 - lỗi tạm (vector store/DB...) -> nak retry
            log.warning("doc_delete_failed error=%s", exc)
            await msg.nak()

    return await broker.subscribe(subject, durable=durable, cb=_cb)
