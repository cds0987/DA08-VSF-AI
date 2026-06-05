from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.domain.entities.ingest_job import IngestJob, IngestJobStatus
from app.interfaces.nats.ingest_consumer import (
    DocDeleteConsumer,
    DocIngestConsumer,
    DocStatusPublisher,
    build_doc_status,
    start_doc_delete_subscription,
    start_doc_ingest_subscription,
)


class FakeIngestUseCase:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[dict] = []
        self.deleted: list[str] = []
        self._fail = fail

    async def enqueue(self, **kwargs):
        if self._fail:
            raise RuntimeError("db down")
        self.calls.append(kwargs)
        return object()

    async def delete(self, document_id: str) -> None:
        if self._fail:
            raise RuntimeError("vector store down")
        self.deleted.append(document_id)


class FakeBroker:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []
        self.subscribed: dict = {}

    async def publish_json(self, subject: str, payload: dict) -> None:
        self.published.append((subject, payload))

    async def subscribe(self, subject, *, durable, cb):
        self.subscribed = {"subject": subject, "durable": durable, "cb": cb}
        return "subscription"


class FakeMsg:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.acked = False
        self.naked = False
        self.termed = False

    async def ack(self):
        self.acked = True

    async def nak(self):
        self.naked = True

    async def term(self):
        self.termed = True


def _job(status: IngestJobStatus, *, chunk_count: int = 0, error: str | None = None) -> IngestJob:
    now = datetime.now(UTC)
    return IngestJob(
        id="job-1",
        document_id="doc-1",
        document_name="Doc",
        file_type="pdf",
        source_uri="s3://b/k.pdf",
        markdown=None,
        artifact_uri=None,
        correlation_id="cid",
        status=status,
        created_at=now,
        updated_at=now,
        chunk_count=chunk_count,
        error_message=error,
    )


# --- consumer.handle: map payload -> enqueue ------------------------------- #
@pytest.mark.asyncio
async def test_handle_maps_payload_to_enqueue() -> None:
    use_case = FakeIngestUseCase()
    consumer = DocIngestConsumer(use_case)
    raw = json.dumps(
        {"doc_id": "d1", "gcs_key": "s3://bucket/x.pdf", "file_type": "pdf"}
    ).encode()

    doc_id = await consumer.handle(raw)

    assert doc_id == "d1"
    call = use_case.calls[0]
    assert call["document_id"] == "d1"
    assert call["source_uri"] == "s3://bucket/x.pdf"  # gcs_key -> source_uri
    assert call["file_type"] == "pdf"
    assert call["markdown"] is None
    assert call["correlation_id"] == "nats:doc.ingest:d1"


@pytest.mark.asyncio
async def test_handle_accepts_s3_key_fallback() -> None:
    # document-service hiện publish s3_key thay vì gcs_key -> vẫn map được (backward-compat).
    use_case = FakeIngestUseCase()
    consumer = DocIngestConsumer(use_case)
    raw = json.dumps(
        {"doc_id": "d1", "s3_key": "s3://bucket/x.pdf", "file_type": "pdf"}
    ).encode()

    doc_id = await consumer.handle(raw)

    assert doc_id == "d1"
    assert use_case.calls[0]["source_uri"] == "s3://bucket/x.pdf"


@pytest.mark.asyncio
async def test_handle_rejects_missing_fields() -> None:
    consumer = DocIngestConsumer(FakeIngestUseCase())
    with pytest.raises(ValueError):
        await consumer.handle(json.dumps({"doc_id": "d1"}).encode())  # thiếu gcs_key/file_type


@pytest.mark.asyncio
async def test_handle_rejects_bad_json() -> None:
    consumer = DocIngestConsumer(FakeIngestUseCase())
    with pytest.raises(ValueError):
        await consumer.handle(b"{not json")


# --- build_doc_status mapping ---------------------------------------------- #
def test_build_doc_status_terminal_and_non_terminal() -> None:
    assert build_doc_status(_job(IngestJobStatus.COMPLETED, chunk_count=5)) == {
        "doc_id": "doc-1",
        "status": "indexed",
        "chunk_count": 5,
    }
    assert build_doc_status(_job(IngestJobStatus.FAILED, error="boom")) == {
        "doc_id": "doc-1",
        "status": "failed",
        "error": "boom",
    }
    assert build_doc_status(_job(IngestJobStatus.PROCESSING)) is None  # chưa terminal


@pytest.mark.asyncio
async def test_status_publisher_publishes_only_terminal() -> None:
    broker = FakeBroker()
    publisher = DocStatusPublisher(broker, subject="doc.status")

    await publisher.publish_for_job(_job(IngestJobStatus.COMPLETED, chunk_count=3))
    await publisher.publish_for_job(_job(IngestJobStatus.PROCESSING))  # bị bỏ qua

    assert broker.published == [("doc.status", {"doc_id": "doc-1", "status": "indexed", "chunk_count": 3})]


@pytest.mark.asyncio
async def test_status_publisher_publishes_failed() -> None:
    broker = FakeBroker()
    publisher = DocStatusPublisher(broker, subject="doc.status")

    await publisher.publish_for_job(_job(IngestJobStatus.FAILED, error="boom"))

    assert broker.published == [("doc.status", {"doc_id": "doc-1", "status": "failed", "error": "boom"})]


@pytest.mark.asyncio
async def test_status_publisher_swallows_broker_error() -> None:
    class FailingBroker:
        async def publish_json(self, subject, payload):
            raise RuntimeError("nats down")

    publisher = DocStatusPublisher(FailingBroker(), subject="doc.status")
    # Publish lỗi không được làm sập worker -> không raise (best-effort, chỉ log).
    await publisher.publish_for_job(_job(IngestJobStatus.COMPLETED, chunk_count=1))


# --- subscription cb: ack / nak / term ------------------------------------- #
@pytest.mark.asyncio
async def test_subscription_acks_on_success() -> None:
    broker = FakeBroker()
    consumer = DocIngestConsumer(FakeIngestUseCase())
    await start_doc_ingest_subscription(
        broker, consumer, subject="doc.ingest", durable="d"
    )
    cb = broker.subscribed["cb"]
    msg = FakeMsg(json.dumps({"doc_id": "d1", "gcs_key": "s3://b/k", "file_type": "pdf"}).encode())

    await cb(msg)

    assert msg.acked and not msg.naked and not msg.termed


@pytest.mark.asyncio
async def test_subscription_terms_poison_payload() -> None:
    broker = FakeBroker()
    consumer = DocIngestConsumer(FakeIngestUseCase())
    await start_doc_ingest_subscription(
        broker, consumer, subject="doc.ingest", durable="d"
    )
    cb = broker.subscribed["cb"]
    msg = FakeMsg(b"{bad json")  # payload hỏng -> term (không gửi lại vô hạn)

    await cb(msg)

    assert msg.termed and not msg.acked and not msg.naked


@pytest.mark.asyncio
async def test_subscription_naks_on_transient_error() -> None:
    broker = FakeBroker()
    consumer = DocIngestConsumer(FakeIngestUseCase(fail=True))  # enqueue lỗi (DB down)
    await start_doc_ingest_subscription(
        broker, consumer, subject="doc.ingest", durable="d"
    )
    cb = broker.subscribed["cb"]
    msg = FakeMsg(json.dumps({"doc_id": "d1", "gcs_key": "s3://b/k", "file_type": "pdf"}).encode())

    await cb(msg)

    assert msg.naked and not msg.acked and not msg.termed


# --- doc.delete consumer ---------------------------------------------------- #
@pytest.mark.asyncio
async def test_delete_handle_calls_delete() -> None:
    use_case = FakeIngestUseCase()
    consumer = DocDeleteConsumer(use_case)

    doc_id = await consumer.handle(json.dumps({"doc_id": "d1"}).encode())

    assert doc_id == "d1"
    assert use_case.deleted == ["d1"]


@pytest.mark.asyncio
async def test_delete_handle_rejects_missing_doc_id() -> None:
    consumer = DocDeleteConsumer(FakeIngestUseCase())
    with pytest.raises(ValueError):
        await consumer.handle(json.dumps({}).encode())


@pytest.mark.asyncio
async def test_delete_subscription_acks_on_success() -> None:
    broker = FakeBroker()
    consumer = DocDeleteConsumer(FakeIngestUseCase())
    await start_doc_delete_subscription(
        broker, consumer, subject="doc.delete", durable="d"
    )
    cb = broker.subscribed["cb"]
    msg = FakeMsg(json.dumps({"doc_id": "d1"}).encode())

    await cb(msg)

    assert msg.acked and not msg.naked and not msg.termed


@pytest.mark.asyncio
async def test_delete_subscription_terms_poison_payload() -> None:
    broker = FakeBroker()
    consumer = DocDeleteConsumer(FakeIngestUseCase())
    await start_doc_delete_subscription(
        broker, consumer, subject="doc.delete", durable="d"
    )
    cb = broker.subscribed["cb"]
    msg = FakeMsg(b"{bad json")

    await cb(msg)

    assert msg.termed and not msg.acked and not msg.naked


@pytest.mark.asyncio
async def test_delete_subscription_naks_on_transient_error() -> None:
    broker = FakeBroker()
    consumer = DocDeleteConsumer(FakeIngestUseCase(fail=True))  # vector store down
    await start_doc_delete_subscription(
        broker, consumer, subject="doc.delete", durable="d"
    )
    cb = broker.subscribed["cb"]
    msg = FakeMsg(json.dumps({"doc_id": "d1"}).encode())

    await cb(msg)

    assert msg.naked and not msg.acked and not msg.termed
