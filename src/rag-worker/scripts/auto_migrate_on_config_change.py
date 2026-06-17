#!/usr/bin/env python3
"""Auto-migration on embed-config change — chạy ở DEPLOY (CI-CD/VM), IDEMPOTENT.

Ý tưởng (tận dụng index_id đã encode model+dim):
  collection đích = VectorStoreConfig.from_env().index_id()
    = {base}__{model_tag}__d{dim}  (vd rag_chatbot__qwen3emb4b__d2560)
  - Đổi EMBED_MODEL/DIMENSION -> index_id MỚI -> collection mới CHƯA tồn tại.
  - Collection CŨ (tên cũ) NGUYÊN VẸN -> "ko vỡ production" tự nhiên.

Logic:
  1. Tính collection đích từ config hiện tại.
  2. Nếu đã tồn tại + có điểm (đã ingest) -> NO-OP (deploy thường, config không đổi).
  3. Nếu CHƯA tồn tại / RỖNG -> config embed ĐỔI -> reset DB status + enqueue reingest
     toàn bộ corpus từ GCS raw/ (force=True). rag-worker auto tạo collection đúng schema
     (named dense+sparse nếu VECTOR_HYBRID=true) lúc upsert đầu.

An toàn:
  - KHÔNG xóa collection nào (collection cũ giữ để rollback; GC thủ công sau khi verify).
  - Idempotent: chạy lại khi collection đã đủ -> no-op. Hợp để gắn vào deploy.
  - --dry-run xem trước; --yes để chạy thật (mặc định chỉ kiểm tra + report).

Chạy trong container rag-worker (có DB + GCS + Qdrant creds):
    python scripts/auto_migrate_on_config_change.py --dry-run
    python scripts/auto_migrate_on_config_change.py --yes
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application.use_cases.ingestion.store_reconciler import parse_object_key  # noqa: E402
from app.interfaces.api.runtime import bootstrap_runtime, build_object_store_lister  # noqa: E402
from core_engine.vectorstore.config import VectorStoreConfig  # noqa: E402


def _qdrant_url() -> str:
    return (os.environ.get("VECTOR_DB_URL") or os.environ.get("QDRANT_URL")
            or "http://qdrant:6333").rstrip("/")


def _qdrant_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = (os.environ.get("VECTOR_DB_API_KEY") or os.environ.get("QDRANT_API_KEY") or "").strip()
    if api_key:
        headers["api-key"] = api_key
    return headers


def _qdrant_request(method: str, path: str) -> dict:
    req = urllib.request.Request(_qdrant_url() + path, method=method, headers=_qdrant_headers())
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return json.loads(raw) if raw else {"status": exc.code}
    except Exception as exc:  # noqa: BLE001 — Qdrant không reachable -> coi như chưa sẵn
        return {"status": "error", "error": str(exc)}


def _collection_ready(name: str) -> bool:
    """True nếu collection tồn tại VÀ có điểm (đã ingest xong) -> không cần migrate."""
    resp = _qdrant_request("GET", f"/collections/{name}")
    if resp.get("status") != "ok":
        return False
    count = resp.get("result", {}).get("points_count")
    return bool(count and int(count) > 0)


def _reset_db_status(database_url: str, dry_run: bool) -> int:
    from sqlalchemy import create_engine, delete, func, select, update
    from sqlalchemy.orm import Session

    from app.infrastructure.db.models import DocumentRecord, IngestJobRecord

    engine = create_engine(database_url, future=True, pool_size=2, max_overflow=0)
    with Session(engine) as session:
        completed = session.execute(
            select(func.count()).where(DocumentRecord.status == "completed")
        ).scalar_one()
        if dry_run:
            print(f"  [dry-run] would reset {completed} docs -> queued")
            return completed
        session.execute(
            update(DocumentRecord).where(DocumentRecord.status == "completed")
            .values(status="queued", chunk_count=0, error_message=None)
        )
        session.execute(
            delete(IngestJobRecord).where(IngestJobRecord.status.in_(["completed", "failed"]))
        )
        session.commit()
    print(f"  rag_db: {completed} docs -> queued")
    return completed


async def _run(dry_run: bool, prefix: str, limit: int | None) -> int:
    config = VectorStoreConfig.from_env()
    target = config.index_id()
    print("=" * 60)
    print("Auto-migration on embed-config change")
    print("=" * 60)
    print(f"  Target collection: {target}")
    print(f"  embed_model/dim  : {config.embed_model} / {config.dimension}")
    print(f"  hybrid (BM25)    : {getattr(config, 'hybrid', False)}")

    if _collection_ready(target):
        print(f"  -> Collection '{target}' đã sẵn (có điểm) => NO-OP (config không đổi).")
        return 0

    print(f"  -> Collection '{target}' CHƯA sẵn => embed-config ĐỔI, kích hoạt reingest.")
    if not dry_run and not os.environ.get("_AUTOMIGRATE_YES"):
        print("  [refuse] cần --yes (hoặc _AUTOMIGRATE_YES=1) cho lần chạy thật.", file=sys.stderr)
        return 2

    rag_db_url = os.environ.get("DATABASE_URL", "")
    if rag_db_url:
        _reset_db_status(rag_db_url, dry_run)
    else:
        print("  [warn] DATABASE_URL trống -> bỏ qua reset DB status")

    runtime = bootstrap_runtime()
    if runtime.ingest_use_case is None or not runtime.source_bucket:
        print("  ERROR: runtime bootstrap fail (ingest_use_case/source_bucket).", file=sys.stderr)
        return 1
    bucket = runtime.source_bucket
    lister = build_object_store_lister(runtime)

    enqueued = 0
    async for obj in lister.list_objects(prefix):
        parsed = parse_object_key(obj.key)
        if parsed is None:
            continue
        doc_id, document_name, file_type = parsed
        if limit is not None and enqueued >= limit:
            break
        if dry_run:
            print(f"  [dry-run] would reingest {doc_id}")
            enqueued += 1
            continue
        await runtime.ingest_use_case.enqueue(
            document_id=doc_id, document_name=document_name, file_type=file_type,
            markdown=None, source_uri=f"s3://{bucket}/{obj.key}",
            correlation_id=f"automigrate:{target}:{doc_id}", force=True,
        )
        enqueued += 1
    print(f"DONE enqueued={enqueued} dry_run={dry_run} -> collection mới '{target}' sẽ tự tạo khi ingest.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="Chỉ kiểm tra + report, không thay đổi.")
    p.add_argument("--yes", action="store_true", help="Bắt buộc cho lần chạy thật.")
    p.add_argument("--prefix", default="raw/", help="Prefix GCS nguồn (default raw/).")
    p.add_argument("--limit", type=int, default=None, help="Giới hạn N doc (thử nghiệm).")
    args = p.parse_args()
    if args.yes:
        os.environ["_AUTOMIGRATE_YES"] = "1"
    return asyncio.run(_run(args.dry_run, args.prefix, args.limit))


if __name__ == "__main__":
    raise SystemExit(main())
