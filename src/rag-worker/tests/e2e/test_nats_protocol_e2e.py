"""E2E giao thức document-service <-> rag-worker với HẠ TẦNG THẬT (giống production).

Hạ tầng (CI dựng bằng docker, xem .github/workflows/rag-service-ci.yml):
  - NATS JetStream  : message bus doc.ingest / doc.status / doc.delete
  - MinIO (S3)      : object storage — file gốc (giả lập GCS/S3 production)
  - Qdrant (riêng)  : vector database

Luồng test:
  document-service (GIẢ LẬP) upload file lên MinIO + publish doc.ingest
    -> rag-worker (THẬT): s3_parser tải từ MinIO -> chunk -> embed(offline) -> upsert Qdrant
    -> publish doc.status=indexed
  document-service (GIẢ LẬP) publish doc.delete
    -> rag-worker (THẬT): xóa vector khỏi Qdrant + metadata

Chỉ phần document-service được giả lập (upload + publish/subscribe message). Toàn bộ phía
rag-worker chạy code thật trên hạ tầng thật — KHÔNG mock, KHÔNG in-process.
Embedding dùng provider `offline` (deterministic) vì CI không có API key OpenAI; mọi thành
phần I/O hạ tầng (S3/Qdrant/NATS) đều thật.

Tự SKIP nếu thiếu NATS_URL / S3_ENDPOINT_URL / VECTOR_DB_URL.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import uuid
from pathlib import Path

import pytest

# tests/e2e/ -> src/rag-worker ; manifest lái corpus (thêm file = thêm entry, ko sửa code)
MANIFEST_PATH = Path(__file__).resolve().parents[2] / "eval" / "validation" / "manifest.json"

NATS_URL = os.getenv("NATS_URL", "").strip()
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "").strip()
VECTOR_DB_URL = os.getenv("VECTOR_DB_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not (NATS_URL and S3_ENDPOINT_URL and VECTOR_DB_URL),
    reason="cần NATS_URL + S3_ENDPOINT_URL + VECTOR_DB_URL (hạ tầng docker) để chạy e2e thật",
)

# tests/e2e/ -> src/rag-worker
RAG_WORKER_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_FILE = RAG_WORKER_ROOT / "eval" / "validation" / "leave_policy.md"
E2E_BUCKET = os.getenv("E2E_S3_BUCKET", "rag-e2e")


def _ensure_uploaded_to_minio(bucket: str, key: str, data: bytes) -> None:
    """document-service GIẢ LẬP: upload file gốc lên MinIO (S3).

    Dùng chính `_default_client_factory` của rag-worker để client upload khớp 100% với
    client download (cùng endpoint/credentials/checksum config).
    """
    from botocore.exceptions import ClientError

    from app.infrastructure.external.s3_parser import _default_client_factory

    client = _default_client_factory()
    try:
        client.create_bucket(Bucket=bucket)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
            raise
    client.put_object(Bucket=bucket, Key=key, Body=data)


def _resolve_collection(prefix: str) -> str | None:
    """Engine đặt tên collection = {VECTOR_COLLECTION}__{model_tag}__d{dimension} -> resolve theo prefix."""
    from qdrant_client import QdrantClient

    client = QdrantClient(url=VECTOR_DB_URL, api_key=os.getenv("VECTOR_DB_API_KEY") or None)
    try:
        for c in client.get_collections().collections:
            if c.name.startswith(prefix):
                return c.name
        return None
    finally:
        client.close()


def _qdrant_point_count(prefix: str) -> int:
    from qdrant_client import QdrantClient

    name = _resolve_collection(prefix)
    if name is None:
        return 0
    client = QdrantClient(url=VECTOR_DB_URL, api_key=os.getenv("VECTOR_DB_API_KEY") or None)
    try:
        return client.count(collection_name=name, exact=True).count
    finally:
        client.close()


@pytest.mark.asyncio
async def test_document_service_to_rag_worker_real_infra() -> None:
    pytest.importorskip("nats")
    pytest.importorskip("boto3")
    pytest.importorskip("qdrant_client")
    import nats

    suffix = uuid.uuid4().hex[:8]
    doc_id = f"e2e-{suffix}"
    collection = f"rag_e2e_{suffix}"
    s3_key = f"raw/{doc_id}/leave_policy.md"
    gcs_key = f"s3://{E2E_BUCKET}/{s3_key}"

    # rag-worker chạy THẬT: parser tải từ MinIO (s3), vector ghi Qdrant remote, embed offline.
    os.environ["APP_ENV"] = "development"
    os.environ["AI_PROVIDER"] = "offline"
    os.environ["PARSER_IMPL"] = "s3"
    os.environ["VECTOR_DB_URL"] = VECTOR_DB_URL
    os.environ["VECTOR_COLLECTION"] = collection  # collection riêng -> count phản ánh đúng doc này
    os.environ["PIPELINE_CONFIG"] = str(RAG_WORKER_ROOT / "config.yaml")

    from app.infrastructure.external.nats_client import NatsBroker
    from app.interfaces.api.runtime import bootstrap_runtime, run_ingest_worker
    from app.interfaces.nats import (
        DocDeleteConsumer,
        DocIngestConsumer,
        DocStatusPublisher,
        start_doc_delete_subscription,
        start_doc_ingest_subscription,
    )

    # --- document-service GIẢ LẬP: upload file gốc lên MinIO ---------------- #
    _ensure_uploaded_to_minio(E2E_BUCKET, s3_key, SAMPLE_FILE.read_bytes())

    stream = f"DOCS_{suffix}"
    ingest_subject = f"doc.ingest.{suffix}"
    status_subject = f"doc.status.{suffix}"
    delete_subject = f"doc.delete.{suffix}"
    logger = logging.getLogger("e2e")

    runtime = bootstrap_runtime()
    assert runtime.ingest_use_case is not None

    broker = NatsBroker(NATS_URL)
    await broker.connect()
    await broker.ensure_stream(stream, [ingest_subject, status_subject, delete_subject])

    publisher = DocStatusPublisher(broker, subject=status_subject, logger=logger)
    ingest_sub = await start_doc_ingest_subscription(
        broker,
        DocIngestConsumer(runtime.ingest_use_case, logger=logger),
        subject=ingest_subject,
        durable=f"ingest_{suffix}",
        logger=logger,
    )
    delete_sub = await start_doc_delete_subscription(
        broker,
        DocDeleteConsumer(runtime.ingest_use_case, logger=logger),
        subject=delete_subject,
        durable=f"delete_{suffix}",
        logger=logger,
    )
    worker = asyncio.create_task(
        run_ingest_worker(
            "e2e-worker", runtime.ingest_use_case, 0.05, logger, publisher.publish_for_job
        )
    )

    # --- document-service GIẢ LẬP: subscribe doc.status -------------------- #
    nc = await nats.connect(NATS_URL)
    js = nc.jetstream()
    statuses: list[dict] = []
    indexed = asyncio.Event()

    async def _on_status(msg) -> None:
        payload = json.loads(msg.data)
        statuses.append(payload)
        await msg.ack()
        if payload.get("status") == "indexed":
            indexed.set()

    status_sub = await js.subscribe(
        status_subject, durable=f"ds_{suffix}", cb=_on_status, manual_ack=True
    )

    try:
        # 1) document-service publish doc.ingest (message giả lập từ BE).
        await broker.publish_json(
            ingest_subject,
            {
                "doc_id": doc_id,
                "gcs_key": gcs_key,
                "file_type": "md",
                "document_name": "leave_policy.md",
                "classification": "internal",
            },
        )

        # 2) rag-worker chạy thật trên hạ tầng thật -> doc.status=indexed.
        await asyncio.wait_for(indexed.wait(), timeout=60.0)
        result = next(s for s in statuses if s.get("status") == "indexed")
        assert result["doc_id"] == doc_id
        assert result["chunk_count"] > 0

        # Vector THẬT đã nằm trong Qdrant.
        assert _qdrant_point_count(collection) > 0

        # 3) document-service publish doc.delete -> rag-worker xóa Qdrant + metadata thật.
        await broker.publish_json(delete_subject, {"doc_id": doc_id})
        for _ in range(120):
            if (
                await runtime.ingest_use_case.get_document(doc_id) is None
                and _qdrant_point_count(collection) == 0
            ):
                break
            await asyncio.sleep(0.25)
        assert await runtime.ingest_use_case.get_document(doc_id) is None
        assert _qdrant_point_count(collection) == 0
    finally:
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
        for sub in (status_sub, ingest_sub, delete_sub):
            with contextlib.suppress(Exception):
                await sub.unsubscribe()
        with contextlib.suppress(Exception):
            await nc.drain()
        with contextlib.suppress(Exception):
            await broker.close()
        with contextlib.suppress(Exception):
            from qdrant_client import QdrantClient

            name = _resolve_collection(collection)
            if name is not None:
                c = QdrantClient(url=VECTOR_DB_URL, api_key=os.getenv("VECTOR_DB_API_KEY") or None)
                c.delete_collection(collection_name=name)
                c.close()


def _load_manifest() -> list[dict]:
    documents = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["documents"]
    assert documents, "validation manifest phải có ít nhất 1 document"
    return documents


@pytest.mark.asyncio
async def test_full_corpus_ingest_delete_real_infra() -> None:
    """TOÀN BỘ corpus text (manifest.json) qua luồng THẬT: NATS + MinIO + Qdrant.

    Khác test 1-file ở trên: data-driven theo manifest -> phủ mọi định dạng parser
    (txt/md/html/docx/pdf/pptx/xlsx). Cũng kiểm 2 hợp đồng THỰC của document-service:
      - publish KEY TRẦN `raw/<id>/<file>` (không scheme) -> consumer ghép s3://bucket/key
      - xóa qua `doc.access(deleted=true)` (document-service KHÔNG gửi doc.delete)
    """
    pytest.importorskip("nats")
    pytest.importorskip("boto3")
    pytest.importorskip("qdrant_client")
    import nats

    manifest = _load_manifest()
    suffix = uuid.uuid4().hex[:8]
    collection = f"rag_e2e_corpus_{suffix}"

    os.environ["APP_ENV"] = "development"
    os.environ["AI_PROVIDER"] = "offline"
    os.environ["PARSER_IMPL"] = "s3"
    os.environ["VECTOR_DB_URL"] = VECTOR_DB_URL
    os.environ["VECTOR_COLLECTION"] = collection
    os.environ["PIPELINE_CONFIG"] = str(RAG_WORKER_ROOT / "config.yaml")

    from app.infrastructure.external.nats_client import NatsBroker
    from app.interfaces.api.runtime import bootstrap_runtime, run_ingest_worker
    from app.interfaces.nats import (
        DocAccessDeleteConsumer,
        DocIngestConsumer,
        DocStatusPublisher,
        start_doc_access_subscription,
        start_doc_ingest_subscription,
    )

    # document-service GIẢ LẬP: upload mọi file gốc lên MinIO dưới key trần raw/<id>/<file>.
    keys: dict[str, str] = {}
    for entry in manifest:
        doc_id = entry["document_id"]
        bare_key = f"raw/{doc_id}/{entry['file']}"
        keys[doc_id] = bare_key
        _ensure_uploaded_to_minio(
            E2E_BUCKET, bare_key, (RAG_WORKER_ROOT / "eval" / "validation" / entry["file"]).read_bytes()
        )

    stream = f"DOCS_{suffix}"
    ingest_subject = f"doc.ingest.{suffix}"
    status_subject = f"doc.status.{suffix}"
    access_subject = f"doc.access.{suffix}"
    logger = logging.getLogger("e2e-corpus")

    runtime = bootstrap_runtime()
    assert runtime.ingest_use_case is not None

    broker = NatsBroker(NATS_URL)
    await broker.connect()
    await broker.ensure_stream(stream, [ingest_subject, status_subject, access_subject])

    publisher = DocStatusPublisher(broker, subject=status_subject, logger=logger)
    # default_bucket=E2E_BUCKET -> consumer ghép key trần thành s3://bucket/key (fix Blocker 1).
    ingest_sub = await start_doc_ingest_subscription(
        broker,
        DocIngestConsumer(runtime.ingest_use_case, default_bucket=E2E_BUCKET, logger=logger),
        subject=ingest_subject,
        durable=f"ingest_{suffix}",
        logger=logger,
    )
    # doc.access(deleted=true) -> xóa (fix Blocker 2: document-service không gửi doc.delete).
    access_sub = await start_doc_access_subscription(
        broker,
        DocAccessDeleteConsumer(runtime.ingest_use_case, logger=logger),
        subject=access_subject,
        durable=f"access_{suffix}",
        logger=logger,
    )
    worker = asyncio.create_task(
        run_ingest_worker(
            "e2e-corpus-worker", runtime.ingest_use_case, 0.05, logger, publisher.publish_for_job
        )
    )

    nc = await nats.connect(NATS_URL)
    js = nc.jetstream()
    indexed: dict[str, dict] = {}
    all_indexed = asyncio.Event()
    expected_ids = {e["document_id"] for e in manifest}

    async def _on_status(msg) -> None:
        payload = json.loads(msg.data)
        await msg.ack()
        if payload.get("status") == "indexed":
            indexed[payload["doc_id"]] = payload
            if expected_ids.issubset(indexed.keys()):
                all_indexed.set()

    status_sub = await js.subscribe(
        status_subject, durable=f"ds_{suffix}", cb=_on_status, manual_ack=True
    )

    try:
        # 1) document-service publish doc.ingest cho TỪNG file (key trần, đúng contract thật).
        for entry in manifest:
            await broker.publish_json(
                ingest_subject,
                {
                    "doc_id": entry["document_id"],
                    "s3_key": keys[entry["document_id"]],  # KEY TRẦN (không s3://)
                    "file_type": entry["file_type"],
                    "document_name": entry["document_name"],
                    "classification": "internal",
                },
            )

        # 2) rag-worker thật xử lý hết -> mọi doc.status=indexed.
        await asyncio.wait_for(all_indexed.wait(), timeout=180.0)
        for entry in manifest:
            payload = indexed[entry["document_id"]]
            assert payload["chunk_count"] > 0, f"{entry['file']} ra 0 chunk"

        # Vector THẬT của cả corpus nằm trong Qdrant.
        assert _qdrant_point_count(collection) >= len(manifest)

        # 3) document-service publish doc.access(deleted=true) cho TỪNG file -> xóa sạch.
        for entry in manifest:
            await broker.publish_json(
                access_subject,
                {"doc_id": entry["document_id"], "deleted": True},
            )
        for _ in range(240):
            gone = [
                e for e in manifest
                if await runtime.ingest_use_case.get_document(e["document_id"]) is None
            ]
            if len(gone) == len(manifest) and _qdrant_point_count(collection) == 0:
                break
            await asyncio.sleep(0.25)
        for entry in manifest:
            assert await runtime.ingest_use_case.get_document(entry["document_id"]) is None
        assert _qdrant_point_count(collection) == 0
    finally:
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
        for sub in (status_sub, ingest_sub, access_sub):
            with contextlib.suppress(Exception):
                await sub.unsubscribe()
        with contextlib.suppress(Exception):
            await nc.drain()
        with contextlib.suppress(Exception):
            await broker.close()
        with contextlib.suppress(Exception):
            from qdrant_client import QdrantClient

            name = _resolve_collection(collection)
            if name is not None:
                c = QdrantClient(url=VECTOR_DB_URL, api_key=os.getenv("VECTOR_DB_API_KEY") or None)
                c.delete_collection(collection_name=name)
                c.close()
