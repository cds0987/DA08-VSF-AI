"""Seed Qdrant với TOÀN BỘ validation corpus qua LUỒNG THẬT (cho e2e rag-worker + mcp).

Khác `seed_qdrant_e2e.py` (1 doc, ingest trực tiếp): script này lái đúng đường
production để mcp-service search lại được trên cùng Qdrant:

  document-service (GIẢ LẬP): upload mọi file trong eval/validation/manifest.json
    lên MinIO (S3) dưới key trần raw/<id>/<file> + publish doc.ingest
      -> rag-worker (THẬT): s3_parser tải từ MinIO -> chunk -> embed(offline) -> Qdrant
      -> publish doc.status=indexed
  Sau khi cả corpus indexed: ghi contract stamp (mcp verify_contract cần stamp này).

KHÁC corpus e2e test ở chỗ: (a) KHÔNG xóa data (để mcp đọc), (b) dùng collection
MẶC ĐỊNH (không override VECTOR_COLLECTION) để index_id khớp đúng cái mcp mong đợi.

Chạy (CI dựng NATS+MinIO+Qdrant bằng docker):
  AI_PROVIDER=offline PARSER_IMPL=s3 \
  NATS_URL=nats://127.0.0.1:4222 \
  S3_ENDPOINT_URL=http://127.0.0.1:9000 \
  S3_ACCESS_KEY_ID=minioadmin S3_SECRET_ACCESS_KEY=minioadmin S3_REGION=us-east-1 \
  E2E_S3_BUCKET=rag-e2e \
  VECTOR_DB_URL=http://127.0.0.1:6333 \
  python scripts/seed_validation_corpus_e2e.py
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path

RAG_WORKER_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_DIR = RAG_WORKER_ROOT / "eval" / "validation"
MANIFEST_PATH = VALIDATION_DIR / "manifest.json"

NATS_URL = os.getenv("NATS_URL", "nats://127.0.0.1:4222").strip()
E2E_BUCKET = os.getenv("E2E_S3_BUCKET", "rag-e2e")

# Producer THẬT chạy offline (CI không có OpenAI key); I/O hạ tầng (S3/NATS/Qdrant) thật.
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("AI_PROVIDER", "offline")
os.environ.setdefault("PARSER_IMPL", "s3")
os.environ.setdefault("PIPELINE_CONFIG", str(RAG_WORKER_ROOT / "config.yaml"))
# CHÚ Ý: KHÔNG set VECTOR_COLLECTION -> dùng default config -> index_id khớp mcp.

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("seed-corpus")


def _load_manifest() -> list[dict]:
    documents = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["documents"]
    assert documents, "validation manifest phải có ít nhất 1 document"
    return documents


def _ensure_uploaded_to_minio(bucket: str, key: str, data: bytes) -> None:
    """document-service GIẢ LẬP: upload file gốc lên MinIO bằng đúng client của rag-worker."""
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


async def _run() -> int:
    import nats

    manifest = _load_manifest()

    from app.interfaces.api.runtime import bootstrap_runtime, run_ingest_worker
    from app.interfaces.nats import (
        DocIngestConsumer,
        DocStatusPublisher,
        start_doc_ingest_subscription,
    )
    from core_engine.vectorstore.qdrant_contract import write_contract_stamp

    # 1) document-service GIẢ LẬP: upload mọi file lên MinIO (key trần raw/<id>/<file>).
    keys: dict[str, str] = {}
    for entry in manifest:
        doc_id = entry["document_id"]
        bare_key = f"raw/{doc_id}/{entry['file']}"
        keys[doc_id] = bare_key
        _ensure_uploaded_to_minio(
            E2E_BUCKET, bare_key, (VALIDATION_DIR / entry["file"]).read_bytes()
        )
    logger.info("uploaded %d files to MinIO bucket=%s", len(manifest), E2E_BUCKET)

    runtime = bootstrap_runtime()
    assert runtime.ingest_use_case is not None

    from app.infrastructure.external.nats_client import NatsBroker

    stream = "DOCS_SEED"
    ingest_subject = "doc.ingest.seed"
    status_subject = "doc.status.seed"

    broker = NatsBroker(NATS_URL)
    await broker.connect()
    await broker.ensure_stream(stream, [ingest_subject, status_subject])

    publisher = DocStatusPublisher(broker, subject=status_subject, logger=logger)
    ingest_sub = await start_doc_ingest_subscription(
        broker,
        DocIngestConsumer(runtime.ingest_use_case, default_bucket=E2E_BUCKET, logger=logger),
        subject=ingest_subject,
        durable="ingest_seed",
        logger=logger,
    )
    worker = asyncio.create_task(
        run_ingest_worker(
            "seed-worker", runtime.ingest_use_case, 0.05, logger, publisher.publish_for_job
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
        status_subject, durable="ds_seed", cb=_on_status, manual_ack=True
    )

    exit_code = 0
    try:
        # 2) document-service GIẢ LẬP: publish doc.ingest cho TỪNG file (key trần).
        for entry in manifest:
            await broker.publish_json(
                ingest_subject,
                {
                    "doc_id": entry["document_id"],
                    "s3_key": keys[entry["document_id"]],  # key trần -> consumer ghép s3://bucket/key
                    "file_type": entry["file_type"],
                    "document_name": entry["document_name"],
                    "classification": "internal",
                },
            )

        # 3) Chờ rag-worker thật ingest hết -> mọi doc.status=indexed.
        await asyncio.wait_for(all_indexed.wait(), timeout=240.0)
        for entry in manifest:
            payload = indexed[entry["document_id"]]
            assert payload["chunk_count"] > 0, f"{entry['file']} ra 0 chunk"
            logger.info(
                "indexed doc=%s chunks=%s", entry["document_id"], payload["chunk_count"]
            )

        # 4) Ghi contract stamp để mcp verify_contract đi qua (KHÔNG xóa data).
        await write_contract_stamp(runtime.vector_config, written_by="rag-worker")
        logger.info(
            "SEED_OK index=%s fingerprint=%s docs=%d",
            runtime.vector_config.index_id(),
            runtime.vector_config.contract().fingerprint,
            len(manifest),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("SEED_FAILED %s", exc)
        exit_code = 1
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
    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
