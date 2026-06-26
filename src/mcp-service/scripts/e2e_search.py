"""E2e mcp-service: rag_search qua rag-worker /api/search THẬT.

mcp = THIN search interface: gọi rag-worker (POST /api/search) rồi rerank. Contract
embed/collection do rag-worker sở hữu (verify ở phía rag-worker, không còn ở mcp).

Exit code:
  0 = search ra >=1 hit (happy path)
  2 = search rỗng (bất thường)

Chạy: RAG_WORKER_URL=http://127.0.0.1:8000 RERANK_PROVIDER=none \
      python scripts/e2e_search.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.search import build_search_service  # noqa: E402

QUERY = "nghỉ phép thường niên"


async def _run() -> int:
    service = build_search_service()
    try:
        hits = await service.rag_search(QUERY, document_ids=["doc1"], top_k=3)
    finally:
        await service.aclose()
    print(f"SEARCH hits={len(hits)}")
    for hit in hits:
        print(f"  - {hit.document_id} score={hit.score:.3f} src={hit.source_gcs_uri}")
    return 0 if hits else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
