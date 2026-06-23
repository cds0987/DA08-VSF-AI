#!/usr/bin/env python3
"""Verify collection BM25 (__s{ver}) TRƯỚC khi cho mcp cutover — điểm test deploy.

Gác 3 thứ, FAIL LOUD (exit != 0 + in lỗi THẬT, KHÔNG nuốt error log):
  1. Schema: named 'dense' + sparse có modifier=IDF (đúng BM25 server-side).
  2. Count > 0 và (nếu source cũ còn) target ~ source (không hụt điểm).
  3. Sparse query CHẠY: lấy 1 điểm, encode bm25_text của nó thành query, query
     using='sparse' -> điểm đó PHẢI nằm trong kết quả. Chứng minh index sparse + IDF
     hoạt động mà KHÔNG cần ai-router (không phụ thuộc embed dense).

Chạy trong container rag-worker:
    python scripts/verify_bm25_collection.py            # exit 0 = sẵn sàng cutover
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core_engine.contract import index_id as build_index_id  # noqa: E402
from core_engine.vectorstore.config import VectorStoreConfig  # noqa: E402
from core_engine.vectorstore.sparse import sparse_encode_query  # noqa: E402


def _client(config: VectorStoreConfig):
    from qdrant_client import QdrantClient

    if config.deployment == "remote":
        return QdrantClient(**config.remote_client_kwargs())
    options = dict(config.options)
    if "location" not in options and "path" not in options:
        options["location"] = ":memory:"
    return QdrantClient(**options)


def run(config: VectorStoreConfig | None = None) -> int:
    from qdrant_client import models

    config = config or VectorStoreConfig.from_env()
    if not config.hybrid:
        print("ERROR: VECTOR_HYBRID tắt -> không có BM25 để verify.", file=sys.stderr)
        return 2
    target = config.index_id()
    source = build_index_id(config.collection, config.embed_model, config.dimension, sparse_version=0)
    print(f"Verify BM25 collection: {target}")

    client = _client(config)
    fail = 0
    try:
        if not client.collection_exists(target):
            print(f"::error:: target '{target}' KHÔNG tồn tại.", file=sys.stderr)
            return 1

        # 1) schema modifier IDF
        info = client.get_collection(target)
        try:
            sparse_cfg = info.config.params.sparse_vectors["sparse"]
            modifier = getattr(sparse_cfg, "modifier", None)
        except Exception:  # noqa: BLE001 — KHÔNG nuốt: in ra rồi fail
            traceback.print_exc()
            print("::error:: không đọc được sparse_vectors config.", file=sys.stderr)
            return 1
        if str(modifier) not in ("Modifier.IDF", "idf") and modifier != models.Modifier.IDF:
            print(f"::error:: sparse modifier = {modifier!r} != IDF -> KHÔNG phải BM25 thật.", file=sys.stderr)
            fail = 1
        else:
            print(f"  [1/3] schema OK: sparse modifier=IDF.")

        # 2) count
        tgt_n = int(client.count(collection_name=target, exact=True).count)
        if tgt_n == 0:
            print("::error:: target rỗng (0 điểm).", file=sys.stderr)
            return 1
        src_n = int(client.count(collection_name=source, exact=True).count) if client.collection_exists(source) else None
        if src_n is not None and tgt_n < src_n:
            print(f"::error:: count hụt: target {tgt_n} < source {src_n} (thiếu {src_n - tgt_n}).", file=sys.stderr)
            fail = 1
        else:
            print(f"  [2/3] count OK: target={tgt_n}" + (f" source={src_n}" if src_n is not None else ""))

        # 3) sparse-only query self-referential
        recs, _ = client.scroll(collection_name=target, with_payload=True, limit=1)
        if not recs:
            print("::error:: không scroll được điểm nào để test query.", file=sys.stderr)
            return 1
        probe = recs[0]
        bm25_text = str((probe.payload or {}).get("bm25_text", "") or "")
        if not bm25_text:
            print("::warning:: điểm mẫu thiếu bm25_text -> bỏ qua test query sparse (sparse có thể rỗng).")
        else:
            idx, val = sparse_encode_query(bm25_text)
            res = client.query_points(
                collection_name=target,
                query=models.SparseVector(indices=idx, values=val),
                using="sparse", limit=10, with_payload=False,
            )
            hit_ids = {p.id for p in res.points}
            if probe.id in hit_ids:
                top = res.points[0].score if res.points else None
                print(f"  [3/3] sparse query OK: điểm mẫu nằm trong kết quả (top_score={top}).")
            else:
                print(f"::error:: sparse query KHÔNG trả về điểm mẫu (id={probe.id}); "
                      f"hits={list(hit_ids)[:5]} -> index sparse/IDF hỏng.", file=sys.stderr)
                fail = 1

        if fail:
            print("::error:: VERIFY FAIL -> KHÔNG cutover mcp. Sửa rồi deploy lại.", file=sys.stderr)
            return 1
        print("VERIFY OK -> sẵn sàng cutover mcp sang collection BM25.")
        return 0
    except Exception:  # noqa: BLE001 — KHÔNG nuốt: full traceback rồi fail
        traceback.print_exc()
        print("::error:: VERIFY lỗi bất ngờ (xem traceback trên).", file=sys.stderr)
        return 1
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
