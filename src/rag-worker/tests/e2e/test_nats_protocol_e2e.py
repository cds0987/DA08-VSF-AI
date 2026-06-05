"""E2E giao thức document-service <-> rag-worker với HẠ TẦNG THẬT (giống production).

Hạ tầng (CI dựng bằng docker, xem .github/workflows/rag-service-ci.yml):
  - NATS JetStream  : message bus doc.ingest / doc.status / doc.access
  - MinIO (S3)      : object storage — file gốc (giả lập GCS/S3 production)
  - Qdrant (riêng)  : vector database

Luồng test:
  document-service (GIẢ LẬP) upload file lên MinIO + publish doc.ingest
    -> rag-worker (THẬT): s3_parser tải từ MinIO -> chunk -> embed(offline) -> upsert Qdrant
    -> publish doc.status=indexed
  document-service (GIẢ LẬP) publish doc.access(deleted=true)
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
from datetime import datetime, timezone
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


def _qdrant_first_payload(prefix: str, document_id: str) -> dict | None:
    """Lấy payload của 1 chunk bất kỳ thuộc document_id (kiểm field đã ghi vào Qdrant)."""
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qm

    name = _resolve_collection(prefix)
    if name is None:
        return None
    client = QdrantClient(url=VECTOR_DB_URL, api_key=os.getenv("VECTOR_DB_API_KEY") or None)
    try:
        points, _ = client.scroll(
            collection_name=name,
            scroll_filter=qm.Filter(
                must=[qm.FieldCondition(key="document_id", match=qm.MatchValue(value=document_id))]
            ),
            limit=1,
            with_payload=True,
        )
        return dict(points[0].payload) if points else None
    finally:
        client.close()


def _faithful_doc_ingest(*, doc_id: str, gcs_uri: str, file_type: str, document_name: str) -> dict:
    """Payload doc.ingest khớp 100% cái document-service THẬT phát (infra/nats/subjects.md):
    URI ĐẦY ĐỦ + document_name + event metadata (event_id/event_version/occurred_at)."""
    return {
        "event_id": str(uuid.uuid4()),
        "event_version": 1,
        "occurred_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "doc_id": doc_id,
        "gcs_key": gcs_uri,  # URI đầy đủ scheme://bucket/key (KHÔNG phải key trần)
        "document_name": document_name,
        "file_type": file_type,
        "classification": "internal",
        "allowed_departments": [],
        "allowed_user_ids": [],
    }


@pytest.mark.asyncio
async def test_corpus_faithful_contract_real_infra() -> None:
    """document-service GIẢ LẬP nhưng payload doc.ingest ĐÚNG 100% contract thật
    (URI đầy đủ + document_name + event metadata) -> rag-worker THẬT ingest cả corpus
    qua NATS+MinIO+Qdrant. Khác test corpus kia (key trần): test này chứng minh hợp đồng
    THẬT chảy thông + các field nhạy (document_name, source_uri) ghi đúng vào Qdrant payload
    (citation hiện tên file thật, không phải UUID).
    """
    pytest.importorskip("nats")
    pytest.importorskip("boto3")
    pytest.importorskip("qdrant_client")
    import nats

    manifest = _load_manifest()
    suffix = uuid.uuid4().hex[:8]
    collection = f"rag_e2e_faithful_{suffix}"

    os.environ["APP_ENV"] = "development"
    os.environ["AI_PROVIDER"] = "offline"
    os.environ["PARSER_IMPL"] = "s3"
    os.environ["VECTOR_DB_URL"] = VECTOR_DB_URL
    os.environ["VECTOR_COLLECTION"] = collection
    os.environ["PIPELINE_CONFIG"] = str(RAG_WORKER_ROOT / "config.yaml")

    from app.infrastructure.external.nats_client import NatsBroker
    from app.interfaces.api.runtime import bootstrap_runtime, run_ingest_worker
    from app.interfaces.nats import (
        DocIngestConsumer,
        DocStatusPublisher,
        start_doc_ingest_subscription,
    )

    # document-service GIẢ LẬP: upload từng file lên MinIO; URI đầy đủ s3://bucket/key.
    uris: dict[str, str] = {}
    for entry in manifest:
        doc_id = entry["document_id"]
        bare_key = f"raw/{doc_id}/{entry['file']}"
        uris[doc_id] = f"s3://{E2E_BUCKET}/{bare_key}"
        _ensure_uploaded_to_minio(
            E2E_BUCKET, bare_key,
            (RAG_WORKER_ROOT / "eval" / "validation" / entry["file"]).read_bytes(),
        )

    stream = f"DOCS_{suffix}"
    ingest_subject = f"doc.ingest.{suffix}"
    status_subject = f"doc.status.{suffix}"
    logger = logging.getLogger("e2e-faithful")

    runtime = bootstrap_runtime()
    assert runtime.ingest_use_case is not None

    broker = NatsBroker(NATS_URL)
    await broker.connect()
    await broker.ensure_stream(stream, [ingest_subject, status_subject])

    publisher = DocStatusPublisher(broker, subject=status_subject, logger=logger)
    # KHÔNG default_bucket: payload đã là URI đầy đủ (đúng contract thật).
    ingest_sub = await start_doc_ingest_subscription(
        broker,
        DocIngestConsumer(runtime.ingest_use_case, logger=logger),
        subject=ingest_subject,
        durable=f"ingest_{suffix}",
        logger=logger,
    )
    worker = asyncio.create_task(
        run_ingest_worker(
            "e2e-faithful-worker", runtime.ingest_use_case, 0.05, logger, publisher.publish_for_job
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
        # 1) publish doc.ingest ĐÚNG contract thật cho từng file.
        for entry in manifest:
            await broker.publish_json(
                ingest_subject,
                _faithful_doc_ingest(
                    doc_id=entry["document_id"],
                    gcs_uri=uris[entry["document_id"]],
                    file_type=entry["file_type"],
                    document_name=entry["document_name"],
                ),
            )

        # 2) rag-worker thật -> mọi doc.status=indexed, chunk_count>0.
        await asyncio.wait_for(all_indexed.wait(), timeout=180.0)
        for entry in manifest:
            assert indexed[entry["document_id"]]["chunk_count"] > 0, f"{entry['file']} ra 0 chunk"

        assert _qdrant_point_count(collection) >= len(manifest)

        # 3) Field nhạy của contract chảy ĐÚNG vào Qdrant payload (deterministic, không cần semantic).
        for entry in manifest:
            doc_id = entry["document_id"]
            payload = _qdrant_first_payload(collection, doc_id)
            assert payload is not None, f"{doc_id} không có point nào trong Qdrant"
            # document_name = tên file thật (citation không hiện UUID).
            assert payload.get("document_name") == entry["document_name"], (
                f"document_name lệch cho {doc_id}: {payload.get('document_name')!r}"
            )
            # source_uri = URI đầy đủ đã publish (lineage để cite nguồn).
            assert payload.get("source_uri") == uris[doc_id], (
                f"source_uri lệch cho {doc_id}: {payload.get('source_uri')!r}"
            )
    finally:
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
        for sub in (status_sub, ingest_sub):
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
        DocAccessDeleteConsumer,
        DocIngestConsumer,
        DocStatusPublisher,
        start_doc_access_subscription,
        start_doc_ingest_subscription,
    )

    # --- document-service GIẢ LẬP: upload file gốc lên MinIO ---------------- #
    _ensure_uploaded_to_minio(E2E_BUCKET, s3_key, SAMPLE_FILE.read_bytes())

    stream = f"DOCS_{suffix}"
    ingest_subject = f"doc.ingest.{suffix}"
    status_subject = f"doc.status.{suffix}"
    access_subject = f"doc.access.{suffix}"
    logger = logging.getLogger("e2e")

    runtime = bootstrap_runtime()
    assert runtime.ingest_use_case is not None

    broker = NatsBroker(NATS_URL)
    await broker.connect()
    await broker.ensure_stream(stream, [ingest_subject, status_subject, access_subject])

    publisher = DocStatusPublisher(broker, subject=status_subject, logger=logger)
    ingest_sub = await start_doc_ingest_subscription(
        broker,
        DocIngestConsumer(runtime.ingest_use_case, logger=logger),
        subject=ingest_subject,
        durable=f"ingest_{suffix}",
        logger=logger,
    )
    access_sub = await start_doc_access_subscription(
        broker,
        DocAccessDeleteConsumer(runtime.ingest_use_case, logger=logger),
        subject=access_subject,
        durable=f"access_{suffix}",
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

        # 3) document-service publish doc.access(deleted=true) -> rag-worker xóa Qdrant + metadata thật.
        await broker.publish_json(access_subject, {"doc_id": doc_id, "deleted": True})
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
