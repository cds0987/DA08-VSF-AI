"""E2e mcp-service: semantic search TOÀN BỘ validation corpus trên Qdrant THẬT.

Tiếp nối `scripts/seed_validation_corpus_e2e.py` của rag-worker: rag-worker đã ingest
cả corpus (qua NATS+MinIO) vào Qdrant; script này đóng vai query-service GIẢ LẬP gọi
tool `rag_search` cho TỪNG golden query trong manifest và assert đúng tài liệu được
retrieve. Ranh giới duy nhất giữa 2 service là Qdrant.

mcp = THIN search interface: gọi rag-worker /api/search rồi rerank; ranh giới giữa 2
service là HTTP endpoint đó (embed + vector search do rag-worker đảm nhiệm). Offline
(CI mặc định): embedding hash không ngữ nghĩa -> đặt RERANK_PROVIDER=lexical +
RERANK_THRESHOLD=0 + SEARCH_TOP_K cao để lexical rerank lái đúng doc lên (kiểm PLUMBING
xuyên 2 service). Chất lượng ngữ nghĩa thật cần provider thật (RAG_EVAL_REAL_PROVIDER=1).

Exit code:
  0 = mọi query retrieve đúng doc kỳ vọng
  1 = có query thiếu doc kỳ vọng

Chạy: RAG_WORKER_URL=http://127.0.0.1:8000 \
      RERANK_PROVIDER=lexical RERANK_THRESHOLD=0 SEARCH_TOP_K=50 \
      python scripts/e2e_search_validation.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.search import build_search_service  # noqa: E402

# scripts/ -> mcp-service -> src ; manifest do rag-worker sở hữu (cùng corpus seed).
MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "rag-worker" / "eval" / "validation" / "manifest.json"
)


def _load_manifest() -> list[dict]:
    documents = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["documents"]
    assert documents, "validation manifest phải có ít nhất 1 document"
    return documents


async def _run() -> int:
    manifest = _load_manifest()
    service = build_search_service()

    misses: list[str] = []
    try:
        for entry in manifest:
            query = entry["query"]
            expected = entry["document_id"]
            hits = await service.rag_search(query, document_ids=None, top_k=5)
            got = [hit.document_id for hit in hits]
            ok = expected in got
            marker = "OK " if ok else "MISS"
            print(f"  [{marker}] q={query!r} expect={expected} got={got}")
            if not ok:
                misses.append(f"{expected} <- {query!r} (got {got})")
    finally:
        await service.aclose()

    if misses:
        print(f"SEARCH_FAILED: {len(misses)}/{len(manifest)} query thiếu doc kỳ vọng:")
        for miss in misses:
            print(f"  - {miss}")
        return 1

    print(f"SEARCH_OK: {len(manifest)}/{len(manifest)} query retrieve đúng doc kỳ vọng")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
