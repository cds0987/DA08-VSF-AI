"""E2e mcp-service: verify contract (fail-closed) + rag_search trên Qdrant THẬT.

Exit code:
  0 = verify OK và search ra >=1 hit (happy path)
  1 = verify contract FAIL (dùng cho test negative/drift — mong đợi exit 1)
  2 = verify OK nhưng search rỗng (bất thường)

Chạy: VECTOR_DB_URL=http://127.0.0.1:6333 AI_PROVIDER=offline RERANK_PROVIDER=none \
      python scripts/e2e_search.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.contract import VectorstoreContractError  # noqa: E402
from app.core.search import build_search_service  # noqa: E402

QUERY = "nghỉ phép thường niên"


async def _run() -> int:
    service = build_search_service()
    try:
        contract = await service.verify_contract()
    except VectorstoreContractError as exc:
        print(f"VERIFY_FAILED: {exc}")
        return 1
    print(f"VERIFY_OK index={contract.index_id} fingerprint={contract.fingerprint}")

    hits = await service.rag_search(QUERY, document_ids=["doc1"], top_k=3)
    print(f"SEARCH hits={len(hits)}")
    for hit in hits:
        print(f"  - {hit.document_id} score={hit.score:.3f} src={hit.source_gcs_uri}")
    return 0 if hits else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
