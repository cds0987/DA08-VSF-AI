"""Đo ĐỘC LẬP recall@k + search-latency cho MỖI collection embed model (multi-collection).

Chạy BÊN TRONG container rag-worker trên prod VM (có ai-router + Qdrant + multi_embed API):

    docker exec -e RECALL_INPUT=/tmp/recall_input.json rag-worker \
        python scripts/per_model_recall.py

Mục tiêu: với 5 collection (primary qwen8b@4096 + 4 secondary e5-large/bge-m3/pplx@1024 +
text-3-small@1536), đo retrieval THẾ NÀO để quyết shard strategy. Đo ĐỘC LẬP từng collection:
embed query bằng ĐÚNG embedder của model đó -> dense vector search trong collection của model
đó -> map candidate về doc-level (document_name) -> recall@1/3/5/10 + MRR; latency p50/p95.

KHÔNG commit, KHÔNG deploy. Script đo, chạy 1 lần.

--- dense-search được gọi NHƯ NÀO --------------------------------------------------------
Pipeline search công khai: SearchUseCase.search -> VectorStore.search(query_vector, query_text,
top_k, document_ids) -> provider.search. Provider qdrant tự phát hiện chế độ collection:
collection có sparse vectors -> 'hybrid' (RRF dense+sparse fusion), ngược lại -> 'dense' trần
(xem core_engine/vectorstore/providers/qdrant/base.py::_collection_mode + _hybrid_query_kwargs/
_dense_query_kwargs).

Để SO EMBEDDING công bằng ta đo DENSE-ONLY: bỏ qua nhánh hybrid (sparse model-agnostic), gọi
thẳng query_points với _dense_query_kwargs (ACL filter = _access_filter(document_ids)). Nếu
collection cũng hybrid, đo THÊM nhánh pipeline (VectorStore.search) để tham chiếu. Tối thiểu
luôn có dense-only. Embedder mỗi model = ProviderEmbeddingService gửi model THẬT qua ai-router
(secondary từ build_embed_targets; primary từ runtime.engine).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import traceback
from dataclasses import dataclass
from typing import Any, Sequence

# Cùng tập đuôi file + chuẩn hóa doc-name như harness recall hiện hữu (eval/openragbench).
_EXTS = (
    ".pdf", ".docx", ".doc", ".txt", ".md", ".markdown",
    ".pptx", ".xlsx", ".html", ".htm",
)
_KS = (1, 3, 5, 10)


def _norm(name: str | None) -> str:
    s = (name or "").strip().lower()
    for ext in _EXTS:
        if s.endswith(ext):
            return s[: -len(ext)]
    return s


def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    i = min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1))))
    return round(s[i], 2)


@dataclass
class _Model:
    """Một collection để đo: tên model + embedder + vectorstore của model đó."""

    embed_model: str
    dimension: int
    collection: str
    embedder: Any   # EmbeddingService (.embed)
    vectors: Any    # VectorStore (.search + .provider)
    is_primary: bool


def _load_models(runtime) -> list[_Model]:
    """Primary (qwen8b từ engine) + secondary (build_embed_targets) = 5 collection.

    primary embedder/vectors LẤY từ runtime.engine (KHÔNG dựng lại) để đúng provider/dim
    đã ghi. secondary build độc lập như ingest đang làm.
    """
    from core_engine.multi_embed import build_embed_targets

    engine = runtime.engine
    if engine is None:
        raise RuntimeError("runtime.engine is None — không bootstrap được engine để đo")

    base_config = engine.vectors.config
    primary_model = base_config.embed_model
    models: list[_Model] = [
        _Model(
            embed_model=primary_model,
            dimension=base_config.dimension,
            collection=base_config.index_id(),
            embedder=engine.embedder,
            vectors=engine.vectors,
            is_primary=True,
        )
    ]
    # secondary: 4 model khác trong embeddings.yaml (primary tự bị loại trong build_embed_targets).
    targets = build_embed_targets(base_config, primary_model=primary_model)
    for t in targets:
        models.append(
            _Model(
                embed_model=t.embed_model,
                dimension=t.dimension,
                collection=t.collection,
                embedder=t.embedder,
                vectors=t.vectors,
                is_primary=False,
            )
        )
    return models


async def _points_count(vectors) -> int | None:
    """Số point trong collection (để skip rỗng). None nếu không lấy được (collection chưa tạo)."""
    provider = getattr(vectors, "provider", None)
    client = getattr(provider, "_client", None)
    collection = getattr(provider, "_collection", None)
    if client is None or collection is None:
        return None
    try:
        if not await client.collection_exists(collection):
            return 0
        info = await client.get_collection(collection)
        # points_count có thể None ngay sau tạo -> coi như 0.
        return int(getattr(info, "points_count", 0) or 0)
    except Exception:  # noqa: BLE001 — không probe được -> chưa biết, để None
        return None


async def _dense_search(vectors, query_vector: Sequence[float], top_k: int,
                        document_ids: Sequence[str] | None) -> list:
    """DENSE-ONLY search (bỏ sparse) -> list SearchHit. Gọi thẳng provider qdrant để
    đo embedding thuần, KHÔNG để RRF/sparse trộn vào. Provider khác qdrant -> fallback
    pipeline .search()."""
    # Dùng PUBLIC pipeline search (xử lý named-vectors dense/sparse đúng cho collection hybrid
    # __s2). Private _dense_query_kwargs gây "Not existing vector name" trên hybrid. query_text=""
    # -> sparse rỗng -> RRF ≈ dense-dominant (đủ để so embedding model).
    return await vectors.search(
        query_vector=query_vector, query_text="",
        top_k=top_k, document_ids=document_ids,
    )


def _ranked_docs(hits, top_k: int) -> list[str]:
    """Dedup candidate -> doc-level ranked list (normalized document_name)."""
    ranked: list[str] = []
    seen: set[str] = set()
    for h in hits:
        d = _norm(getattr(h, "document_name", None))
        if d and d not in seen:
            seen.add(d)
            ranked.append(d)
    return ranked[:top_k]


def _score(rows: list[dict]) -> dict:
    """rows: [{gt, ranked}] -> recall@k + MRR doc-level."""
    hits = {k: 0 for k in _KS}
    rr = 0.0
    n = len(rows)
    for row in rows:
        gt = _norm(row["gt"])
        ranked = row["ranked"]
        rank = ranked.index(gt) + 1 if gt in ranked else None
        if rank:
            rr += 1.0 / rank
            for k in _KS:
                if rank <= k:
                    hits[k] += 1
    return {
        "mrr": round(rr / n, 3) if n else 0.0,
        "recall": {f"@{k}": round(hits[k] / n, 3) if n else 0.0 for k in _KS},
    }


async def _eval_model(m: _Model, queries: list[dict], doc_ids: list[str],
                      top_k: int) -> dict:
    """Đo 1 collection: embed + dense search từng query -> recall + latency. An toàn:
    lỗi -> trả status error, KHÔNG ném (model khác vẫn chạy)."""
    points = await _points_count(m.vectors)
    base = {
        "model": m.embed_model,
        "collection": m.collection,
        "dimension": m.dimension,
        "is_primary": m.is_primary,
        "points_count": points,
        "n_query": 0,
    }
    if points == 0:
        return {**base, "status": "skipped_empty"}

    embed_ms: list[float] = []
    search_ms: list[float] = []
    total_ms: list[float] = []
    rows: list[dict] = []
    errors = 0
    for q in queries:
        gt = q.get("gt_id") or q.get("gt_doc_id") or q.get("gt")
        text = q["query"]
        try:
            t0 = time.perf_counter()
            vec = await m.embedder.embed(text)
            t1 = time.perf_counter()
            hits = await _dense_search(m.vectors, vec, top_k, doc_ids)
            t2 = time.perf_counter()
        except Exception as exc:  # noqa: BLE001 — 1 query lỗi không làm vỡ cả model
            errors += 1
            rows.append({"gt": gt, "ranked": []})
            if errors <= 3:
                base.setdefault("query_errors", []).append(str(exc)[:160])
            continue
        embed_ms.append((t1 - t0) * 1000.0)
        search_ms.append((t2 - t1) * 1000.0)
        total_ms.append((t2 - t0) * 1000.0)
        rows.append({"gt": gt, "ranked": _ranked_docs(hits, top_k)})

    scored = _score(rows)
    return {
        **base,
        "status": "ok" if errors < len(queries) else "all_queries_failed",
        "n_query": len(queries),
        "query_errors_count": errors,
        "recall": scored["recall"],
        "mrr": scored["mrr"],
        "latency_ms": {
            "embed_p50": _pct(embed_ms, 50), "embed_p95": _pct(embed_ms, 95),
            "search_p50": _pct(search_ms, 50), "search_p95": _pct(search_ms, 95),
            "total_p50": _pct(total_ms, 50), "total_p95": _pct(total_ms, 95),
        },
    }


def _print_table(results: list[dict]) -> None:
    hdr = (
        f"{'model':<26} {'n':>4} "
        f"{'r@1':>6} {'r@3':>6} {'r@5':>6} {'r@10':>6} {'MRR':>6} "
        f"{'emb_p50':>8} {'emb_p95':>8} {'srch_p50':>9} {'srch_p95':>9} "
        f"{'points':>8} {'status':<16}"
    )
    print("\n=== PER-MODEL DENSE RECALL@k + LATENCY (independent per collection) ===")
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        rec = r.get("recall", {})
        lat = r.get("latency_ms", {})
        pts = r.get("points_count")
        print(
            f"{r['model']:<26} {r.get('n_query', 0):>4} "
            f"{rec.get('@1', 0):>6} {rec.get('@3', 0):>6} {rec.get('@5', 0):>6} "
            f"{rec.get('@10', 0):>6} {r.get('mrr', 0):>6} "
            f"{lat.get('embed_p50', 0):>8} {lat.get('embed_p95', 0):>8} "
            f"{lat.get('search_p50', 0):>9} {lat.get('search_p95', 0):>9} "
            f"{('?' if pts is None else pts):>8} {r.get('status', '?'):<16}"
        )


async def _amain() -> None:
    from app.interfaces.api.runtime import bootstrap_runtime

    input_path = os.getenv("RECALL_INPUT", "/tmp/recall_input.json")
    with open(input_path, encoding="utf-8") as fh:
        data = json.load(fh)
    doc_ids = data["doc_ids"]
    queries = data["queries"]
    top_k = int(data.get("top_k", 10))

    runtime = bootstrap_runtime()
    models = _load_models(runtime)
    print(
        f"[per_model_recall] input={input_path} | {len(doc_ids)} doc ACL | "
        f"{len(queries)} query | top_k={top_k} | {len(models)} collection"
    )

    results: list[dict] = []
    for m in models:
        try:
            res = await _eval_model(m, queries, doc_ids, top_k)
        except Exception as exc:  # noqa: BLE001 — 1 model lỗi không vỡ model khác
            res = {
                "model": m.embed_model, "collection": m.collection,
                "is_primary": m.is_primary, "status": "error",
                "error": str(exc)[:200], "trace": traceback.format_exc()[-600:],
            }
        results.append(res)
        print(f"  done {m.embed_model} -> {res.get('status')}")

    _print_table(results)
    payload = {"top_k": top_k, "n_doc_acl": len(doc_ids), "n_query": len(queries),
               "models": results}
    print("RESULT=" + json.dumps(payload, ensure_ascii=False))


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
