#!/usr/bin/env python3
"""Multi-collection APPEND-migrate + BACKFILL từ MD cache (KHÔNG re-parse/OCR).

Đọc embeddings.yaml -> với mỗi embed model active tính collection (index_id). So với
Qdrant LIVE:
  - collection CHƯA có  -> CREATE (đúng dim/schema). [APPEND]
  - collection CÓ rồi   -> GIỮ NGUYÊN (no-op).
  - model BỎ khỏi config-> KHÔNG đụng collection cũ (không delete).

BACKFILL (--backfill): với mọi doc đã ingest (DB completed), ĐỌC MD từ ArtifactStore
(artifact_uri) -> chunk + embed (model mới) -> upsert collection thiếu. BỎ QUA parse/OCR
(không gọi parser). Idempotent (chunk_id ổn định -> upsert đè). MD artifact thiếu -> log skip.

Chạy TRONG container rag-worker (DB + Qdrant + ai-router creds):
    python scripts/multi_embed_migrate.py --dry-run            # report append + backfill plan
    python scripts/multi_embed_migrate.py --yes                # tạo collection thiếu (no backfill) — NHANH
    python scripts/multi_embed_migrate.py --backfill-new --yes # tạo + backfill CHỈ collection vừa created (CI/CD)
    python scripts/multi_embed_migrate.py --backfill --yes     # tạo + backfill TOÀN corpus từ MD (thủ công)
    python scripts/multi_embed_migrate.py --backfill --limit 5 --yes

CI/CD: deploy chạy `--yes` (tạo collection thiếu, blocking, fast) rồi LAUNCH `--backfill-new --yes`
detached (nền). Deploy thường (config không đổi) -> 0 collection created -> backfill-new no-op.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.entities.document import DocumentStatus  # noqa: E402
from app.interfaces.api.runtime import bootstrap_runtime  # noqa: E402
from core_engine.engine import HaystackRagEngine, IngestInput  # noqa: E402
from core_engine.logging_utils import log_event  # noqa: E402
from core_engine.multi_embed import build_embed_targets  # noqa: E402
import logging  # noqa: E402


async def _ensure_collection(target) -> str:
    """Tạo collection target nếu chưa có (idempotent qua provider _ensure).

    Trả trạng thái phân biệt "created" (collection VỪA tạo lần này) vs "exists" (đã có)
    -> caller chỉ backfill collection "created" (tránh re-embed corpus đã có mỗi deploy).
    Kiểm tra collection_exists TRƯỚC khi _ensure (idempotent, không delete) để biết được
    trạng thái cũ; _ensure tự CREATE nếu thiếu, no-op nếu có -> APPEND không-delete.
    """
    provider = getattr(target.vectors, "provider", None)
    ensure = getattr(provider, "_ensure", None)
    if ensure is None:
        return "no-ensure"
    existed = None
    client = getattr(provider, "_client", None)
    collection = getattr(provider, "_collection", None)
    if client is not None and collection is not None:
        try:
            existed = await client.collection_exists(collection)
        except Exception:  # noqa: BLE001 - không xác định được -> coi như exists (an toàn: KHÔNG backfill)
            existed = True
    await ensure()
    if existed is None:
        return "ensured"
    return "exists" if existed else "created"


async def _collection_point_count(target) -> int | None:
    """Số điểm trong collection target. Dùng cho backfill-EMPTY (points=0) — robust hơn
    "created-this-run": CI/CD tạo collection ở run TRƯỚC (one-shot --yes) -> run backfill
    thấy "exists" dù collection RỖNG -> phải dựa EMPTINESS, không phải created-flag.
    None = không xác định (an toàn: KHÔNG backfill)."""
    provider = getattr(target.vectors, "provider", None)
    client = getattr(provider, "_client", None)
    collection = getattr(provider, "_collection", None)
    if client is None or collection is None:
        return None
    try:
        if not await client.collection_exists(collection):
            return 0
        info = await client.get_collection(collection)
        return int(getattr(info, "points_count", 0) or 0)
    except Exception:  # noqa: BLE001 - không xác định -> None -> không backfill (an toàn)
        return None


async def _backfill_target(
    engine_settings,
    captioner,
    chunker,
    target,
    documents,
    artifact_store,
    *,
    limit: int | None,
    dry_run: bool,
    logger: logging.Logger,
) -> tuple[int, int, int]:
    """Re-embed mọi doc completed vào collection của target từ MD cache. (done, skipped, failed)."""
    # Engine TẠM với primary = (embedder, vectors) CỦA TARGET -> ingest(markdown) embed+upsert
    # đúng collection target. KHÔNG parser -> KHÔNG parse/OCR (markdown lấy từ ArtifactStore).
    backfill_engine = HaystackRagEngine(
        settings=engine_settings,
        embedder=target.embedder,
        vectors=target.vectors,
        captioner=captioner,
        chunker=chunker,
    )
    done = skipped = failed = 0
    offset = 0
    page = 100
    while True:
        docs = await documents.list_all(limit=page, offset=offset)
        if not docs:
            break
        offset += len(docs)
        for doc in docs:
            if doc.status is not DocumentStatus.COMPLETED:
                continue
            if limit is not None and done >= limit:
                return done, skipped, failed
            artifact_uri = artifact_store.artifact_uri_for(doc.id)
            try:
                markdown = await artifact_store.read_markdown(artifact_uri)
            except Exception as exc:  # noqa: BLE001 - MD thiếu -> skip, KHÔNG re-parse
                skipped += 1
                log_event(
                    logger, logging.INFO, "backfill_skip_no_artifact",
                    stage="backfill", document_id=doc.id,
                    collection=target.collection, error=str(exc)[:200],
                )
                continue
            if not (markdown or "").strip():
                skipped += 1
                continue
            if dry_run:
                done += 1
                print(f"  [dry-run] would backfill {doc.id} -> {target.collection}")
                continue
            try:
                await backfill_engine.ingest(
                    IngestInput(
                        document_id=doc.id,
                        document_name=doc.name,
                        file_type=doc.file_type,
                        markdown=markdown,
                        artifact_uri=artifact_uri,
                        correlation_id=f"backfill:{target.collection}:{doc.id}",
                    )
                )
                done += 1
            except Exception as exc:  # noqa: BLE001 - 1 doc fail không giết cả backfill
                failed += 1
                log_event(
                    logger, logging.WARNING, "backfill_doc_failed",
                    stage="backfill", document_id=doc.id,
                    collection=target.collection, error=str(exc)[:300],
                )
    return done, skipped, failed


async def _run(dry_run: bool, backfill: bool, backfill_new: bool, limit: int | None) -> int:
    logger = logging.getLogger("multi_embed_migrate")
    runtime = bootstrap_runtime()
    if runtime.engine is None:
        print("ERROR: engine bootstrap fail -> abort", file=sys.stderr)
        return 1
    base_config = runtime.engine.vectors.config
    targets = build_embed_targets(base_config, primary_model=base_config.embed_model)
    do_backfill = backfill or backfill_new
    mode_label = ""
    if backfill:
        mode_label = " + BACKFILL(all)"
    elif backfill_new:
        mode_label = " + BACKFILL(new-only)"
    print("=" * 60)
    print("Multi-collection APPEND-migrate" + mode_label)
    print("=" * 60)
    print(f"  Primary collection : {base_config.index_id()} (giữ nguyên)")
    print(f"  Secondary targets  : {len(targets)}")
    for t in targets:
        print(f"    - {t.embed_model:38s} d{t.dimension} -> {t.collection}")
    if not targets:
        print("  (không có model secondary trong embeddings.yaml) -> no-op.")
        return 0

    # APPEND: tạo collection thiếu (idempotent), KHÔNG xóa. Theo dõi collection nào VỪA created.
    created_collections: set[str] = set()
    for t in targets:
        if dry_run:
            print(f"  [dry-run] ensure collection {t.collection}")
            continue
        status = await _ensure_collection(t)
        if status == "created":
            created_collections.add(t.collection)
        print(f"  ensure {t.collection}: {status}")

    if not do_backfill:
        print("DONE (append-only; chạy --backfill / --backfill-new để re-embed corpus từ MD).")
        return 0

    # backfill-new: CHỈ backfill collection RỖNG (points=0) — robust với CI/CD (create ở run
    # trước -> "exists" nhưng rỗng -> vẫn backfill). Collection ĐÃ có data -> skip (idempotent,
    # deploy thường nhanh + không re-embed corpus đã có). --backfill (thủ công): TẤT CẢ target.
    if backfill_new and not dry_run:
        backfill_targets = []
        for t in targets:
            n = await _collection_point_count(t)
            print(f"  {t.collection}: points={n}")
            if n == 0:  # RỖNG (mới tạo / chưa backfill) -> backfill. None (không rõ) -> skip an toàn.
                backfill_targets.append(t)
        if not backfill_targets:
            print("backfill-new: mọi collection đã có data -> NO-OP (deploy thường nhanh).")
            return 0
        print(f"backfill-empty: backfill collection RỖNG: "
              f"{[t.collection for t in backfill_targets]}")
    else:
        backfill_targets = targets
        if backfill:
            print(f"backfill(all): backfill TẤT CẢ {len(targets)} target (thủ công).")

    documents = runtime.document_repository
    artifact_store = runtime.artifact_store
    primary_engine = runtime.engine
    total = {}
    for t in backfill_targets:
        d, s, f = await _backfill_target(
            primary_engine.settings, primary_engine.captioner, primary_engine.chunker,
            t, documents, artifact_store, limit=limit, dry_run=dry_run, logger=logger,
        )
        total[t.collection] = (d, s, f)
        print(f"  backfill {t.collection}: done={d} skipped={s} failed={f}")
    print(f"DONE backfill dry_run={dry_run} -> {total}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--dry-run", action="store_true", help="Report append + backfill plan.")
    p.add_argument("--yes", action="store_true", help="Bắt buộc cho lần chạy thật.")
    p.add_argument("--backfill", action="store_true",
                   help="Re-embed TOÀN corpus từ MD cache (thủ công).")
    p.add_argument("--backfill-new", action="store_true",
                   help="Re-embed CHỈ collection vừa created lần này (CI/CD nền).")
    p.add_argument("--limit", type=int, default=None, help="Giới hạn N doc/backfill (thử).")
    args = p.parse_args()
    if not args.dry_run and not args.yes:
        print("Từ chối: lần chạy thật phải có --yes (hoặc --dry-run).", file=sys.stderr)
        return 2
    return asyncio.run(_run(args.dry_run, args.backfill, args.backfill_new, args.limit))


if __name__ == "__main__":
    raise SystemExit(main())
