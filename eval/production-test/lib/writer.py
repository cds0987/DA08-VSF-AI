from __future__ import annotations

import asyncio
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")


def percentile(values: list[float], pct: float) -> float | None:
    clean = sorted(v for v in values if isinstance(v, (int, float)))
    if not clean:
        return None
    index = (len(clean) - 1) * pct
    lower = int(index)
    upper = min(lower + 1, len(clean) - 1)
    if lower == upper:
        return float(clean[lower])
    return float(clean[lower] + (clean[upper] - clean[lower]) * (index - lower))


def latency_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    first = [
        float(row["first_token_latency_seconds"])
        for row in rows
        if row.get("first_token_latency_seconds") is not None
    ]
    total = [
        float(row["total_latency_seconds"])
        for row in rows
        if row.get("total_latency_seconds") is not None
    ]
    return {
        "first_token_latency_p50_seconds": statistics.median(first) if first else None,
        "first_token_latency_p95_seconds": percentile(first, 0.95),
        "response_latency_p50_seconds": statistics.median(total) if total else None,
        "response_latency_p95_seconds": percentile(total, 0.95),
    }


class RunWriter:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self._lock = asyncio.Lock()

    async def append(self, filename: str, data: Any) -> None:
        async with self._lock:
            append_jsonl(self.run_dir / filename, data)

    def touch_outputs(self) -> None:
        for name in ("golden_qa_used.jsonl", "qa_results.jsonl", "retrieval_results.jsonl", "sse_events.jsonl"):
            path = self.run_dir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)


def write_report(path: Path, *, dataset: str, summary: dict[str, Any]) -> None:
    lines = [
        f"# Production Evidence Run: {dataset}",
        "",
        "This run records raw production evidence only. It does not compute RAGAS, safety, or business scores.",
        "",
        "## Counts",
        f"- Total: `{summary.get('total')}`",
        f"- Completed: `{summary.get('completed')}`",
        f"- Timed out: `{summary.get('timed_out')}`",
        f"- Failed: `{summary.get('failed')}`",
        f"- Auth refreshes: `{summary.get('auth_refresh_count')}`",
        f"- Re-logins: `{summary.get('relogin_count')}`",
        "",
        "## Latency",
        f"- First token p50: `{summary.get('first_token_latency_p50_seconds')}`",
        f"- First token p95: `{summary.get('first_token_latency_p95_seconds')}`",
        f"- Response p50: `{summary.get('response_latency_p50_seconds')}`",
        f"- Response p95: `{summary.get('response_latency_p95_seconds')}`",
        "",
        "## Evidence",
        "- `qa_results.jsonl`: questions, answers, sources, latency, status, auth recovery.",
        "- `retrieval_results.jsonl`: retrieved/probed context evidence for later RAG metrics.",
        "- `sse_events.jsonl`: raw JSON-safe SSE events from production.",
        "- `golden_qa_used.jsonl`: selected golden QA metadata.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
