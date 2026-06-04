#!/usr/bin/env python
"""Benchmark harness — đo per-stage time + memory + recall theo cấu hình env hiện tại.

Tận dụng đúng tính "tháo-lắp bằng 1 dòng env" của service: KHÔNG nhận tham số model/
backend trên CLI — script chỉ đọc môi trường (AI_PROVIDER, EMBED_MODEL, VECTOR_DB_*,
RERANK_PROVIDER, CAPTION_ENABLED, chunk/retrieval knobs...) rồi dựng engine qua
`build_engine()`. Muốn A/B: đổi 1 dòng `.env` (hoặc export) rồi chạy lại script.

Cách đo:
- Per-stage time: gắn một log handler bắt event `ingest_completed`/`search_completed`/
  `ocr_extracted` do engine phát ra (V5-6), đọc các field `*_ms` — KHÔNG đo lại độc lập,
  nên số khớp đúng những gì code production tự ghi.
- Memory: `tracemalloc` bao quanh toàn bộ vòng ingest+search, báo peak (MB).
- Recall@k: corpus golden nhỏ, mỗi query đúng 1 tài liệu liên quan.

Chạy (từ thư mục src/rag-service):
    python scripts/benchmark.py                 # offline mặc định
    AI_PROVIDER=offline python scripts/benchmark.py --repeat 20
    RERANK_PROVIDER=none python scripts/benchmark.py
    python scripts/benchmark.py --csv bench.csv # append một dòng CSV để gom nhiều run

Lưu ý: provider thật (AI_PROVIDER=openai + key) sẽ gọi network và phát sinh chi phí.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import statistics
import sys
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core_engine import IngestInput, build_engine  # noqa: E402
from core_engine.ai import get_ai_provider, reset_ai_provider  # noqa: E402
from core_engine.config import load_settings  # noqa: E402
from core_engine.factory import (  # noqa: E402
    caption_enabled_from_env,
    rerank_provider_from_env,
)
from core_engine.logging_utils import _EVENT_FIELDS_ATTR  # noqa: E402
from core_engine.vectorstore import VectorStoreConfig  # noqa: E402

_CORPUS = [
    IngestInput(
        document_id="doc-account",
        document_name="Account Guide",
        file_type="md",
        markdown="# Reset password\nVao Cai dat > Bao mat de dat lai mat khau. "
        "Lien ket dat lai mat khau het han sau 15 phut.\n",
        source_uri="s3://knowledge/account.md",
        artifact_uri="artifact://doc-account",
    ),
    IngestInput(
        document_id="doc-hr",
        document_name="HR Guide",
        file_type="md",
        markdown="# Leave policy\nNhan vien full-time co 12 ngay nghi phep nam. "
        "Quan ly phe duyet tren he thong HR.\n",
        source_uri="s3://knowledge/hr.md",
        artifact_uri="artifact://doc-hr",
    ),
    IngestInput(
        document_id="doc-finance",
        document_name="Finance Guide",
        file_type="md",
        markdown="# Expense reimbursement\nChi phi cong tac can nop hoa don trong 30 ngay "
        "de duoc hoan ung.\n",
        source_uri="s3://knowledge/finance.md",
        artifact_uri="artifact://doc-finance",
    ),
]

_QUERIES = [
    ("reset mat khau het han bao lau", "doc-account"),
    ("nhan vien co bao nhieu ngay nghi phep nam", "doc-hr"),
    ("nop hoa don cong tac trong bao nhieu ngay", "doc-finance"),
]


class _EventCapture(logging.Handler):
    """Bắt structured events của engine để đọc field `*_ms` (per-stage timing)."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[str, dict]] = []

    def emit(self, record: logging.LogRecord) -> None:
        event = getattr(record, "event", None)
        if event is None:
            return
        fields = {
            name: getattr(record, name, None)
            for name in getattr(record, _EVENT_FIELDS_ATTR, ())
        }
        self.events.append((event, fields))

    def field_values(self, event: str, field: str) -> list[float]:
        return [
            value
            for name, fields in self.events
            if name == event
            for value in (fields.get(field),)
            if isinstance(value, (int, float))
        ]


def _summary(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    p95 = (
        statistics.quantiles(ordered, n=20, method="inclusive")[-1]
        if len(ordered) > 1
        else ordered[0]
    )
    return {
        "n": len(ordered),
        "p50_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(p95, 3),
        "mean_ms": round(statistics.fmean(ordered), 3),
        "max_ms": round(max(ordered), 3),
    }


async def _run(repeat: int, top_k: int) -> dict:
    reset_ai_provider()
    provider = get_ai_provider()
    settings = load_settings()
    vector_config = VectorStoreConfig.from_env()
    capture = _EventCapture()
    root = logging.getLogger()
    root.addHandler(capture)
    previous_level = root.level
    root.setLevel(logging.INFO)

    tracemalloc.start()
    try:
        engine = build_engine(provider=provider)
        for document in _CORPUS:
            await engine.ingest(document)

        recalls: list[float] = []
        for _ in range(repeat):
            for query, relevant_id in _QUERIES:
                results = await engine.search(query, top_k=top_k, rerank_threshold=0.0)
                retrieved = [r.document_id for r in results[:top_k]]
                recalls.append(1.0 if relevant_id in retrieved else 0.0)
        current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        root.removeHandler(capture)
        root.setLevel(previous_level)

    return {
        "config": {
            "ai_provider": provider.name,
            "embed_model": os.getenv("EMBED_MODEL", "") or "(offline/default)",
            "embed_dimension": settings.embed_dimension,
            "vector_provider": vector_config.provider,
            "vector_deployment": vector_config.deployment,
            "rerank_provider": rerank_provider_from_env(),
            "caption_enabled": caption_enabled_from_env(),
            "top_k_candidates": settings.top_k_candidates,
            "rerank_top_k": top_k,
        },
        "ingest": {
            "documents": len(_CORPUS),
            "total_ms": _summary(capture.field_values("ingest_completed", "total_ms")),
            "split_ms": _summary(capture.field_values("ingest_completed", "split_ms")),
            "caption_ms": _summary(capture.field_values("ingest_completed", "caption_ms")),
            "embed_ms": _summary(capture.field_values("ingest_completed", "embed_ms")),
            "vector_write_ms": _summary(
                capture.field_values("ingest_completed", "vector_write_ms")
            ),
        },
        "search": {
            "queries": len(_QUERIES) * repeat,
            "total_ms": _summary(capture.field_values("search_completed", "total_ms")),
            "embed_ms": _summary(capture.field_values("search_completed", "embed_ms")),
            "vector_search_ms": _summary(
                capture.field_values("search_completed", "vector_search_ms")
            ),
            "rerank_ms": _summary(capture.field_values("search_completed", "rerank_ms")),
            "recall_at_k": round(statistics.fmean(recalls), 3) if recalls else 0.0,
        },
        "ocr": {
            "pages_per_second": _summary(
                capture.field_values("ocr_extracted", "pages_per_second")
            ),
        },
        "memory": {
            "current_mb": round(current / (1024 * 1024), 3),
            "peak_mb": round(peak / (1024 * 1024), 3),
        },
    }


def _append_csv(path: Path, report: dict) -> None:
    row = {
        "ai_provider": report["config"]["ai_provider"],
        "embed_model": report["config"]["embed_model"],
        "embed_dimension": report["config"]["embed_dimension"],
        "vector_provider": report["config"]["vector_provider"],
        "vector_deployment": report["config"]["vector_deployment"],
        "rerank_provider": report["config"]["rerank_provider"],
        "caption_enabled": report["config"]["caption_enabled"],
        "ingest_total_p95_ms": report["ingest"]["total_ms"].get("p95_ms"),
        "search_total_p95_ms": report["search"]["total_ms"].get("p95_ms"),
        "search_embed_p95_ms": report["search"]["embed_ms"].get("p95_ms"),
        "search_vector_p95_ms": report["search"]["vector_search_ms"].get("p95_ms"),
        "search_rerank_p95_ms": report["search"]["rerank_ms"].get("p95_ms"),
        "recall_at_k": report["search"]["recall_at_k"],
        "peak_mb": report["memory"]["peak_mb"],
    }
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repeat", type=int, default=10, help="lần lặp mỗi query để p95 ổn định"
    )
    parser.add_argument("--top-k", type=int, default=3, help="rerank_top_k khi search")
    parser.add_argument(
        "--csv", type=Path, default=None, help="append một dòng tổng hợp vào file CSV"
    )
    args = parser.parse_args()

    report = asyncio.run(_run(repeat=max(1, args.repeat), top_k=max(1, args.top_k)))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.csv is not None:
        _append_csv(args.csv, report)
        print(f"\n[csv] appended -> {args.csv}", file=sys.stderr)


if __name__ == "__main__":
    main()
