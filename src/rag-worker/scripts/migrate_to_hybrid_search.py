#!/usr/bin/env python3
"""Migrate Qdrant collection sang schema hybrid search (dense + sparse named vectors).

Quy trình 3 bước:

  Bước 0 — Reset trạng thái DB (rag_db + doc_db) về 'queued' để UI không hiện
            'indexed' khi Qdrant đã trống. rag_db tự cập nhật khi worker hoàn
            thành. doc_db cập nhật qua NATS doc.status sau khi ingest xong.

  Bước 1 — Xóa collection Qdrant cũ (unnamed vector, không tương thích hybrid
            search). rag-worker auto tạo lại đúng schema (named dense + sparse)
            khi upsert đầu tiên.

  Bước 2 — Enqueue re-ingest toàn bộ corpus từ GCS với force=True.
            Worker đang chạy nhặt job PENDING -> re-parse -> caption -> embed
            -> upsert. doc_db nhận NATS doc.status sau mỗi doc hoàn thành.

Chạy TRONG container rag-worker (có DB + GCS + Qdrant creds):

    # Xem trước không làm gì
    docker compose exec rag-worker python scripts/migrate_to_hybrid_search.py --dry-run

    # Thử 3 doc đầu (kiểm tra schema mới)
    docker compose exec rag-worker python scripts/migrate_to_hybrid_search.py --limit 3 --yes

    # Chạy thật toàn bộ
    docker compose exec rag-worker python scripts/migrate_to_hybrid_search.py --yes

    # Bỏ qua reset doc_db (không có DOC_DATABASE_URL)
    docker compose exec rag-worker python scripts/migrate_to_hybrid_search.py --yes --skip-doc-db

    # Chỉ reset DB, không re-ingest (debug)
    docker compose exec rag-worker python scripts/migrate_to_hybrid_search.py --yes --only-reset-db

WARNING: Bước 1 xóa collection = mất search tạm thời. Nên chạy off-hours.
         Theo dõi: docker compose logs -f rag-worker | grep ingest_completed
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


# ─── Qdrant REST helpers ────────────────────────────────────────────────────

def _qdrant_url() -> str:
    return (
        os.environ.get("VECTOR_DB_URL")
        or os.environ.get("QDRANT_URL")
        or "http://qdrant:6333"
    ).rstrip("/")


def _qdrant_headers() -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    api_key = (
        os.environ.get("VECTOR_DB_API_KEY") or os.environ.get("QDRANT_API_KEY") or ""
    ).strip()
    if api_key:
        headers["api-key"] = api_key
    return headers


def _qdrant_request(method: str, path: str, body: dict | None = None) -> dict:
    url = _qdrant_url() + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=_qdrant_headers())
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return json.loads(raw) if raw else {"status": exc.code}


def _collection_exists(name: str) -> bool:
    resp = _qdrant_request("GET", f"/collections/{name}")
    return resp.get("status") == "ok"


def _collection_is_hybrid(name: str) -> bool:
    """True nếu collection đã có named vector 'sparse' (schema mới)."""
    resp = _qdrant_request("GET", f"/collections/{name}")
    if resp.get("status") != "ok":
        return False
    params = resp.get("result", {}).get("config", {}).get("params", {})
    return bool(params.get("sparse_vectors", {}))


def _delete_collection(name: str) -> bool:
    resp = _qdrant_request("DELETE", f"/collections/{name}")
    return resp.get("status") in ("ok", "acknowledged")


# ─── DB reset helpers ────────────────────────────────────────────────────────

def _reset_rag_db(database_url: str, dry_run: bool) -> int:
    """Reset rag_db.documents + xóa ingest_jobs cũ (completed/failed)."""
    from sqlalchemy import create_engine, delete, func, select, text, update
    from sqlalchemy.orm import Session

    from app.infrastructure.db.models import DocumentRecord, IngestJobRecord

    engine = create_engine(database_url, future=True, pool_size=2, max_overflow=0)
    with Session(engine) as session:
        # Đếm để report
        completed_docs = session.execute(
            select(func.count()).where(DocumentRecord.status == "completed")
        ).scalar_one()
        old_jobs = session.execute(
            select(func.count()).where(IngestJobRecord.status.in_(["completed", "failed"]))
        ).scalar_one()

        if dry_run:
            print(
                f"[dry-run] would reset {completed_docs} docs (rag_db.documents: "
                f"completed -> queued, chunk_count=0)"
            )
            print(
                f"[dry-run] would delete {old_jobs} old ingest_jobs "
                f"(status completed/failed)"
            )
            return completed_docs

        # Reset document status
        session.execute(
            update(DocumentRecord)
            .where(DocumentRecord.status == "completed")
            .values(status="queued", chunk_count=0, error_message=None)
        )
        # Xóa job cũ để không gây nhầm lẫn với các job PENDING mới
        # (unique partial index chỉ áp dụng với pending/processing/stale nên xóa completed ok)
        session.execute(
            delete(IngestJobRecord).where(IngestJobRecord.status.in_(["completed", "failed"]))
        )
        session.commit()

    print(
        f"  rag_db.documents : {completed_docs} docs -> status='queued', chunk_count=0"
    )
    print(f"  rag_db.ingest_jobs: {old_jobs} completed/failed jobs đã xóa")
    return completed_docs


def _reset_doc_db(doc_database_url: str, dry_run: bool) -> int:
    """Reset doc_db (doc_svc.documents) status từ 'indexed' về 'queued'.

    doc_svc dùng schema riêng 'doc_svc' trong cùng Postgres với rag_db.
    URL thường = thay rag_db -> doc_db: postgresql+psycopg://postgres:PW@host/doc_db
    """
    from sqlalchemy import create_engine, func, select, text, update
    from sqlalchemy.orm import Session

    engine = create_engine(doc_database_url, future=True, pool_size=2, max_overflow=0)
    with Session(engine) as session:
        indexed_count = session.execute(
            text("SELECT COUNT(*) FROM doc_svc.documents WHERE status = 'indexed' AND deleted_at IS NULL")
        ).scalar_one()

        if dry_run:
            print(
                f"[dry-run] would reset {indexed_count} docs "
                f"(doc_db.doc_svc.documents: indexed -> queued, chunk_count=0)"
            )
            return indexed_count

        result = session.execute(
            text(
                "UPDATE doc_svc.documents "
                "SET status = 'queued', chunk_count = 0, error_message = NULL, "
                "    updated_at = NOW() "
                "WHERE status = 'indexed' AND deleted_at IS NULL"
            )
        )
        session.commit()
        count = result.rowcount

    print(f"  doc_db.doc_svc.documents: {count} docs -> status='queued', chunk_count=0")
    return count


# ─── Main logic ─────────────────────────────────────────────────────────────

async def _run(
    limit: int | None,
    dry_run: bool,
    prefix: str,
    skip_drop: bool,
    skip_doc_db: bool,
    only_reset_db: bool,
) -> int:
    config = VectorStoreConfig.from_env()
    collection_name = config.index_id()
    qdrant_base = _qdrant_url()
    rag_db_url = os.environ.get("DATABASE_URL", "")
    doc_db_url = os.environ.get(
        "DOC_DATABASE_URL",
        rag_db_url.replace("/rag_db", "/doc_db") if rag_db_url else "",
    )

    print("=" * 60)
    print("Migrate to Hybrid Search")
    print("=" * 60)
    print(f"  Collection     : {collection_name}")
    print(f"  Qdrant URL     : {qdrant_base}")
    print(f"  rag_db         : {rag_db_url.split('@')[-1] if rag_db_url else '(không có)'}")
    print(f"  doc_db         : {doc_db_url.split('@')[-1] if doc_db_url else '(không có)'}")
    print(f"  GCS prefix     : {prefix}")
    print(f"  Dry-run        : {dry_run}")
    print()

    # ── Bước 0: reset DB status ──────────────────────────────────────────────
    print("── Bước 0: Reset DB status ─────────────────────────────────────────")

    if not rag_db_url:
        print("[warn] DATABASE_URL trống, bỏ qua reset rag_db")
    else:
        try:
            _reset_rag_db(rag_db_url, dry_run)
        except Exception as exc:
            print(f"[error] reset rag_db thất bại: {exc}", file=sys.stderr)
            return 1

    if skip_doc_db:
        print("[skip] --skip-doc-db: bỏ qua reset doc_db")
    elif not doc_db_url:
        print(
            "[warn] DOC_DATABASE_URL không có và không tự suy được -> bỏ qua reset doc_db.\n"
            "       Đặt DOC_DATABASE_URL=postgresql+psycopg://postgres:PW@app-postgres:5432/doc_db\n"
            "       hoặc chạy thủ công:\n"
            "         docker compose exec app-postgres psql -U postgres -d doc_db -c \\\n"
            "           \"UPDATE doc_svc.documents SET status='queued', chunk_count=0, "
            "error_message=NULL WHERE status='indexed' AND deleted_at IS NULL;\""
        )
    else:
        try:
            _reset_doc_db(doc_db_url, dry_run)
        except Exception as exc:
            print(
                f"[warn] reset doc_db thất bại ({exc}) — tiếp tục (UI sẽ lag, không mất data)."
            )

    print()

    if only_reset_db:
        print("[stop] --only-reset-db: dừng sau bước 0.")
        return 0

    # ── Bước 1: xóa collection Qdrant ───────────────────────────────────────
    print("── Bước 1: Xóa collection Qdrant ───────────────────────────────────")

    if skip_drop:
        print("[skip] --skip-drop: bỏ qua xóa collection")
    else:
        exists = _collection_exists(collection_name)
        if not exists:
            print(f"  Collection '{collection_name}' chưa tồn tại -> bỏ qua")
        else:
            schema_ok = _collection_is_hybrid(collection_name)
            schema_label = "hybrid (dense+sparse)" if schema_ok else "cũ (unnamed vector)"
            print(f"  Collection '{collection_name}' tồn tại, schema: {schema_label}")
            if dry_run:
                print(f"  [dry-run] would DELETE '{collection_name}'")
            else:
                print(f"  Đang xóa collection '{collection_name}'...")
                ok = _delete_collection(collection_name)
                if ok:
                    print("  OK — collection đã xóa. Schema mới sẽ được tạo lúc ingest đầu tiên.")
                else:
                    print("  FAIL — không xóa được collection, abort.", file=sys.stderr)
                    return 1

    print()

    # ── Bước 2: enqueue re-ingest ─────────────────────────────────────────────
    print("── Bước 2: Enqueue re-ingest toàn bộ corpus ────────────────────────")
    print("  Bootstrap rag-worker runtime...")

    runtime = bootstrap_runtime()
    if runtime.ingest_use_case is None:
        print("  ERROR: ingest_use_case None (engine bootstrap fail)", file=sys.stderr)
        return 1
    bucket = runtime.source_bucket
    if not bucket:
        print("  ERROR: source_bucket trống (cần S3_SOURCE_BUCKET)", file=sys.stderr)
        return 1
    lister = build_object_store_lister(runtime)

    print(f"  Liệt kê objects từ gs://{bucket}/{prefix} ...")
    scanned = 0
    enqueued = 0
    async for obj in lister.list_objects(prefix):
        parsed = parse_object_key(obj.key)
        if parsed is None:
            continue
        doc_id, document_name, file_type = parsed
        scanned += 1
        if limit is not None and enqueued >= limit:
            print(f"  [info] Đã đạt giới hạn --limit {limit}, dừng.")
            break
        if dry_run:
            print(f"  [dry-run] would re-ingest {doc_id} ({document_name})")
            enqueued += 1
            continue
        await runtime.ingest_use_case.enqueue(
            document_id=doc_id,
            document_name=document_name,
            file_type=file_type,
            markdown=None,
            source_uri=f"s3://{bucket}/{obj.key}",
            correlation_id=f"migrate_hybrid:{doc_id}",
            force=True,
        )
        enqueued += 1
        print(f"  enqueued {doc_id} ({document_name})")

    print()
    print("=" * 60)
    print(f"DONE  scanned={scanned}  enqueued={enqueued}  dry_run={dry_run}")

    if not dry_run and enqueued > 0:
        print()
        print("Theo dõi tiến trình:")
        print(f"  docker compose logs -f rag-worker | grep ingest_completed")
        print(f"  # Kiểm tra schema mới trên Qdrant:")
        print(f"  curl {qdrant_base}/collections/{collection_name} | python -m json.tool")

    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--limit", type=int, default=None, metavar="N",
                   help="Chỉ enqueue N doc đầu (thử trước khi chạy toàn bộ).")
    p.add_argument("--dry-run", action="store_true",
                   help="In ra sẽ làm gì, không thay đổi gì.")
    p.add_argument("--prefix", default="raw/", metavar="PREFIX",
                   help="Prefix object nguồn trong GCS bucket (default: raw/).")
    p.add_argument("--skip-drop", action="store_true",
                   help="Bỏ qua bước xóa collection Qdrant (đã xóa thủ công).")
    p.add_argument("--skip-doc-db", action="store_true",
                   help="Bỏ qua reset doc_db (không có kết nối hoặc tự làm thủ công).")
    p.add_argument("--only-reset-db", action="store_true",
                   help="Chỉ chạy bước 0 (reset DB), không xóa Qdrant, không re-ingest.")
    p.add_argument("--yes", action="store_true",
                   help="Bắt buộc cho lần chạy thật. Thiếu -> chỉ dry-run an toàn.")
    args = p.parse_args()

    if not args.dry_run and not args.yes:
        print(
            "Từ chối: lần chạy thật phải có --yes. Dùng --dry-run để xem trước.",
            file=sys.stderr,
        )
        return 2

    return asyncio.run(
        _run(
            args.limit,
            args.dry_run,
            args.prefix,
            args.skip_drop,
            args.skip_doc_db,
            args.only_reset_db,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
