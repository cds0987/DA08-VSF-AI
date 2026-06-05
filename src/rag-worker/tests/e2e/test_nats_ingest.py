"""NATS JetStream integration test (opt-in) — chứng minh phần transport THẬT mà
unit-test (broker giả) không phủ: connect -> ensure_stream -> durable subscribe ->
ack, và doc.status publish round-trip qua broker thật.

Tự SKIP nếu chưa set NATS_URL. CI dựng NATS JetStream container rồi set NATS_URL.

Chạy local:
    nats-server -js &
    NATS_URL=nats://localhost:4222 pytest tests/e2e/test_nats_ingest.py -q
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime

import pytest

from app.domain.entities.ingest_job import IngestJob, IngestJobStatus
from app.infrastructure.external.nats_client import NatsBroker
from app.interfaces.nats import (
    DocIngestConsumer,
    DocStatusPublisher,
    start_doc_ingest_subscription,
)

NATS_URL = os.getenv("NATS_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not NATS_URL, reason="set NATS_URL to run the NATS JetStream integration test"
)


class _RecordingIngest:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.event = asyncio.Event()

    async def enqueue(self, **kwargs):
        self.calls.append(kwargs)
        self.event.set()
        return object()


@pytest.mark.asyncio
async def test_doc_ingest_roundtrip_enqueues_and_acks() -> None:
    pytest.importorskip("nats")
    suffix = uuid.uuid4().hex[:8]
    stream = f"DOCS_{suffix}"
    ingest_subject = f"doc.ingest.{suffix}"
    status_subject = f"doc.status.{suffix}"

    broker = NatsBroker(NATS_URL)
    await broker.connect()
    await broker.ensure_stream(stream, [ingest_subject, status_subject])

    recorder = _RecordingIngest()
    consumer = DocIngestConsumer(recorder)
    sub = await start_doc_ingest_subscription(
        broker,
        consumer,
        subject=ingest_subject,
        durable=f"ingest_{suffix}",
        queue=f"q_{suffix}",
    )
    try:
        await broker.publish_json(
            ingest_subject,
            {"doc_id": "t1", "gcs_key": "s3://bucket/x.pdf", "file_type": "pdf"},
        )
        await asyncio.wait_for(recorder.event.wait(), timeout=10.0)
        call = recorder.calls[0]
        assert call["document_id"] == "t1"
        assert call["source_uri"] == "s3://bucket/x.pdf"  # gcs_key -> source_uri
        assert call["file_type"] == "pdf"
    finally:
        await sub.unsubscribe()
        await broker.close()


@pytest.mark.asyncio
async def test_doc_status_publish_roundtrip() -> None:
    import nats

    suffix = uuid.uuid4().hex[:8]
    stream = f"STATUS_{suffix}"
    status_subject = f"doc.status.{suffix}"

    broker = NatsBroker(NATS_URL)
    await broker.connect()
    await broker.ensure_stream(stream, [status_subject])

    nc = await nats.connect(NATS_URL)
    js = nc.jetstream()
    received: list[dict] = []
    got = asyncio.Event()

    async def _cb(msg):
        received.append(json.loads(msg.data))
        await msg.ack()
        got.set()

    psub = await js.subscribe(
        status_subject, durable=f"status_{suffix}", cb=_cb, manual_ack=True
    )
    try:
        job = IngestJob(
            id="j1",
            document_id="t1",
            document_name="Doc",
            file_type="pdf",
            source_uri=None,
            markdown=None,
            artifact_uri=None,
            correlation_id=None,
            status=IngestJobStatus.COMPLETED,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            chunk_count=4,
        )
        publisher = DocStatusPublisher(broker, subject=status_subject)
        await publisher.publish_for_job(job)
        await asyncio.wait_for(got.wait(), timeout=10.0)
        assert received[0] == {"doc_id": "t1", "status": "indexed", "chunk_count": 4}
    finally:
        await psub.unsubscribe()
        await nc.drain()
        await broker.close()
