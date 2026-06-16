#!/usr/bin/env python3
"""Re-ingest TOÀN BỘ corpus (vd sau khi đổi EMBED_TARGET) -> embed lại vector mới.

Đổi cách embed KHÔNG đổi collection (model+dim giữ nguyên) nên vector cũ vẫn stale
tới khi re-ingest. Script này liệt kê mọi object nguồn trong GCS (`raw/<doc_id>/<file>`)
rồi enqueue lại job ingest với force=True (bỏ qua skip-completed). Worker đang chạy của
rag-worker service sẽ nhặt job PENDING -> re-parse (OCR cache theo content-hash) -> embed
theo EMBED_TARGET hiện tại -> upsert đè chunk_id (idempotent).

Chạy TRONG container rag-worker (có DB + GCS creds):
    python scripts/reingest_all.py --dry-run            # chỉ liệt kê, không enqueue
    python scripts/reingest_all.py --limit 5 --yes      # re-ingest 5 doc đầu (thử)
    python scripts/reingest_all.py --yes                # re-ingest TẤT CẢ

An toàn: idempotent (chạy lại được); --yes bắt buộc cho lần chạy thật; --limit để thử.
Nên chạy off-hours + theo dõi RAM VM + log `ingest_completed`/`langsmith_root_posted`.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application.use_cases.ingestion.store_reconciler import parse_object_key  # noqa: E402
from app.infrastructure.external.s3_parser import current_storage_uri_scheme  # noqa: E402
from app.interfaces.api.runtime import (  # noqa: E402
    bootstrap_runtime,
    build_object_store_lister,
)


async def _run(limit: int | None, dry_run: bool, prefix: str) -> int:
    runtime = bootstrap_runtime()
    if runtime.ingest_use_case is None:
        print("ERROR: ingest_use_case None (engine bootstrap fail) -> abort", file=sys.stderr)
        return 1
    bucket = runtime.source_bucket
    if not bucket:
        print("ERROR: source_bucket trống (cần S3_SOURCE_BUCKET) -> abort", file=sys.stderr)
        return 1
    lister = build_object_store_lister(runtime)

    scanned = 0
    enqueued = 0
    async for obj in lister.list_objects(prefix):
        parsed = parse_object_key(obj.key)
        if parsed is None:
            continue
        doc_id, document_name, file_type = parsed
        scanned += 1
        if limit is not None and enqueued >= limit:
            break
        if dry_run:
            print(f"[dry-run] would re-ingest {doc_id} ({document_name})")
            enqueued += 1
            continue
        await runtime.ingest_use_case.enqueue(
            document_id=doc_id,
            document_name=document_name,
            file_type=file_type,
            markdown=None,
            source_uri=f"{current_storage_uri_scheme()}://{bucket}/{obj.key}",
            correlation_id=f"reingest:{doc_id}",
            force=True,
        )
        enqueued += 1
        print(f"enqueued re-ingest {doc_id} ({document_name})")

    print(f"DONE scanned={scanned} enqueued={enqueued} dry_run={dry_run}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--limit", type=int, default=None, help="Chỉ re-ingest N doc đầu (thử).")
    p.add_argument("--dry-run", action="store_true", help="Chỉ liệt kê, không enqueue.")
    p.add_argument("--prefix", default="raw/", help="Prefix object nguồn trong bucket.")
    p.add_argument("--yes", action="store_true", help="Bắt buộc cho lần chạy THẬT (không dry-run).")
    args = p.parse_args()
    if not args.dry_run and not args.yes:
        print("Từ chối: lần chạy thật phải có --yes (hoặc dùng --dry-run).", file=sys.stderr)
        return 2
    return asyncio.run(_run(args.limit, args.dry_run, args.prefix))


if __name__ == "__main__":
    raise SystemExit(main())
