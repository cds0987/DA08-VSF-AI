#!/usr/bin/env python3
"""Migrate SPARSE (BM25) bằng SCROLL-COPY — KHÔNG re-embed, KHÔNG reingest từ GCS.

VÌ SAO scroll-copy: đổi thuật toán sparse (BM25 thật, Modifier.IDF) chỉ cần TÍNH LẠI sparse
value; dense vector + payload GIỮ NGUYÊN. Đọc thẳng collection cũ (đã có dense + payload
bm25_text), recompute sparse, ghi sang collection MỚI (__s{ver}). Rẻ (không tốn ai-router),
blue-green (collection cũ nguyên vẹn để rollback), không "chạy lại toàn bộ pipeline".

  source = index_id(..., sparse_version=0)   (collection hybrid hiện tại, không hậu tố)
  target = config.index_id()                 (collection BM25 mới, __s{SPARSE_ENCODING_VERSION})

AN TOÀN / LOG LỖI THẬT (yêu cầu vận hành — TUYỆT ĐỐI không nuốt error):
  - Mọi lỗi batch -> in FULL traceback + point ids -> exit != 0 (CI/deploy ĐỎ, không xanh giả).
  - Đối chiếu count: points(target) PHẢI == points(source); lệch -> FAIL loud.
  - Đếm điểm thiếu dense / thiếu bm25_text -> log rõ (sparse rỗng = chỉ search được dense).
  - Qdrant unreachable / source rỗng -> exit != 0 (caller tự quyết fallback).
  - Idempotent: target đã đủ điểm -> NO-OP.
  - Ghi dấu niêm (stamp) cho target -> mcp verify_contract pass (nếu thiếu mcp fail-closed).

Chạy trong container rag-worker:
    python scripts/migrate_sparse_version.py --dry-run
    python scripts/migrate_sparse_version.py --yes
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core_engine.contract import build_contract_stamp, meta_collection_name  # noqa: E402
from core_engine.contract import index_id as build_index_id  # noqa: E402
from core_engine.vectorstore.config import VectorStoreConfig  # noqa: E402
from core_engine.vectorstore.providers.qdrant.base import point_id  # noqa: E402
from core_engine.vectorstore.sparse import (  # noqa: E402
    BM25_AVGDL,
    sparse_encode_document,
)


def _client(config: VectorStoreConfig):
    from qdrant_client import QdrantClient

    if config.deployment == "remote":
        return QdrantClient(**config.remote_client_kwargs())
    options = dict(config.options)
    if "location" not in options and "path" not in options:
        options["location"] = ":memory:"
    return QdrantClient(**options)


def _points_count(client, name: str) -> int | None:
    try:
        return int(client.count(collection_name=name, exact=True).count)
    except Exception:  # noqa: BLE001 — collection chưa tồn tại -> None (phân biệt với 0)
        return None


def _ensure_target(client, config: VectorStoreConfig, target: str) -> None:
    """Tạo target ĐÚNG schema hybrid BM25 (named dense + sparse modifier=IDF) nếu chưa có."""
    from qdrant_client import models

    if client.collection_exists(target):
        return
    client.create_collection(
        collection_name=target,
        vectors_config={
            "dense": models.VectorParams(
                size=config.dimension, distance=models.Distance.COSINE
            ),
        },
        sparse_vectors_config={
            "sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)
        },
    )
    # Payload index document_id (filter scoped-search; Qdrant Cloud bắt buộc).
    client.create_payload_index(
        collection_name=target, field_name="document_id", field_schema="keyword"
    )
    print(f"  tạo target '{target}' (named dense + sparse modifier=IDF) OK")


def _write_stamp(client, config: VectorStoreConfig) -> None:
    """Ghi dấu niêm contract cho target -> mcp verify_contract pass (fail-closed nếu thiếu)."""
    from qdrant_client import models

    contract = config.contract()
    payload = build_contract_stamp(contract)
    payload["written_by"] = "migrate_sparse_version"
    meta = meta_collection_name(config.collection)
    if not client.collection_exists(meta):
        client.create_collection(
            collection_name=meta,
            vectors_config=models.VectorParams(size=1, distance=models.Distance.COSINE),
        )
    client.upsert(
        collection_name=meta,
        points=[
            models.PointStruct(
                id=point_id(f"__contract__::{contract.index_id}"), vector=[1.0], payload=payload
            )
        ],
    )
    print(f"  ghi stamp contract cho '{contract.index_id}' (fingerprint={contract.fingerprint})")


def run(dry_run: bool, batch: int, limit: int | None, config: VectorStoreConfig | None = None) -> int:
    from qdrant_client import models

    config = config or VectorStoreConfig.from_env()
    if not config.hybrid:
        print("ERROR: VECTOR_HYBRID tắt -> không có sparse để migrate. ABORT.", file=sys.stderr)
        return 2
    target = config.index_id()
    source = build_index_id(
        config.collection, config.embed_model, config.dimension, sparse_version=0
    )

    print("=" * 64)
    print("Migrate SPARSE (BM25) — scroll-copy (giữ dense, tính lại sparse)")
    print("=" * 64)
    print(f"  source : {source}")
    print(f"  target : {target}")
    print(f"  avgdl  : {BM25_AVGDL} (env BM25_AVGDL) | dry_run={dry_run} batch={batch} limit={limit}")

    if source == target:
        print("ERROR: source == target (sparse_version=0?) -> không có gì để migrate.", file=sys.stderr)
        return 2

    client = _client(config)
    try:
        src_count = _points_count(client, source)
        if src_count is None:
            print(f"ERROR: source '{source}' KHÔNG tồn tại -> không scroll-copy được "
                  "(caller nên fallback reingest GCS).", file=sys.stderr)
            return 1
        if src_count == 0:
            print(f"ERROR: source '{source}' RỖNG (0 điểm) -> không có dữ liệu để copy.", file=sys.stderr)
            return 1
        print(f"  source có {src_count} điểm.")

        tgt_count = _points_count(client, target)
        if tgt_count is not None and tgt_count >= src_count:
            print(f"  target '{target}' đã đủ điểm ({tgt_count} >= {src_count}) => NO-OP (idempotent).")
            return 0

        if dry_run:
            print(f"  [dry-run] would scroll-copy {src_count} điểm {source} -> {target} "
                  "(recompute sparse BM25, giữ dense) + ghi stamp.")
            return 0

        _ensure_target(client, config, target)

        copied = 0
        empty_sparse = 0
        no_dense = 0
        dl_sum = 0
        dl_n = 0
        errors = 0
        offset = None
        while True:
            records, offset = client.scroll(
                collection_name=source,
                with_payload=True,
                with_vectors=True,
                limit=batch,
                offset=offset,
            )
            if not records:
                break
            points = []
            batch_ids = [r.id for r in records]
            try:
                for r in records:
                    vectors = r.vector or {}
                    # source hybrid -> named {"dense": [...], "sparse": old}. Chỉ tái dùng dense.
                    dense = vectors.get("dense") if isinstance(vectors, dict) else vectors
                    if not dense:
                        no_dense += 1
                        continue
                    payload = dict(r.payload or {})
                    bm25_text = str(payload.get("bm25_text", "") or "")
                    idx, val = sparse_encode_document(bm25_text)
                    if not idx:
                        empty_sparse += 1
                    else:
                        toks = len([t for t in bm25_text.lower().split()])  # xấp xỉ dl cho avgdl
                        dl_sum += toks
                        dl_n += 1
                    points.append(
                        models.PointStruct(
                            id=r.id,
                            vector={
                                "dense": list(dense),
                                "sparse": models.SparseVector(indices=list(idx), values=list(val)),
                            },
                            payload=payload,
                        )
                    )
                if points:
                    client.upsert(collection_name=target, points=points, wait=True)
                    copied += len(points)
            except Exception:  # noqa: BLE001 — KHÔNG nuốt: in full traceback + ids rồi đánh dấu fail
                errors += 1
                print(f"::error:: batch lỗi (ids={batch_ids[:10]}...) — traceback:", file=sys.stderr)
                traceback.print_exc()
            if limit is not None and copied >= limit:
                print(f"  [limit] đạt {limit} -> dừng (thử nghiệm).")
                break
            if offset is None:
                break
            print(f"  ... copied={copied}/{src_count}")

        _write_stamp(client, config)

        # ── Đối chiếu count (FAIL LOUD nếu lệch) ───────────────────────────────
        final = _points_count(client, target) or 0
        avg_measured = (dl_sum / dl_n) if dl_n else 0.0
        print("-" * 64)
        print(f"  copied={copied} target_count={final} source_count={src_count}")
        print(f"  no_dense={no_dense} empty_sparse={empty_sparse} batch_errors={errors}")
        print(f"  avgdl ĐO ĐƯỢC ≈ {avg_measured:.1f} token/chunk "
              f"(env BM25_AVGDL={BM25_AVGDL}). Cân nhắc set BM25_AVGDL≈{avg_measured:.0f} "
              "để length-norm khớp corpus (non-fatal nếu khác).")

        if errors:
            print(f"::error:: có {errors} batch lỗi -> migrate KHÔNG toàn vẹn. ĐỎ.", file=sys.stderr)
            return 1
        if limit is None and final < src_count:
            print(f"::error:: count lệch: target {final} < source {src_count} "
                  f"(thiếu {src_count - final}). ĐỎ — KHÔNG cutover.", file=sys.stderr)
            return 1
        print("  OK — scroll-copy toàn vẹn. Target sẵn sàng để mcp cutover.")
        return 0
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="Chỉ kiểm tra + report, không ghi.")
    p.add_argument("--yes", action="store_true", help="Bắt buộc cho lần chạy thật.")
    p.add_argument("--batch", type=int, default=256, help="Kích thước scroll/upsert batch.")
    p.add_argument("--limit", type=int, default=None, help="Giới hạn N điểm (thử nghiệm).")
    args = p.parse_args()
    if not args.dry_run and not args.yes:
        print("Từ chối: lần chạy thật phải có --yes (hoặc --dry-run).", file=sys.stderr)
        return 2
    return run(args.dry_run, args.batch, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
