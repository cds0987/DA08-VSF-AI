from __future__ import annotations

import os
from statistics import quantiles
from time import perf_counter

import pytest

from haystack_interface import IngestInput, OfflineProvider, build_engine
from haystack_interface.ai import get_ai_provider, reset_ai_provider

"""Structural eval gate by default, real-provider eval when explicitly enabled.

Offline mode proves retrieval plumbing: lineage fields, top-hit recall on a fixed corpus,
correlation propagation, and no-answer threshold behavior. It does NOT claim production
quality for caption/model/prompt changes because embeddings are synthetic.

Set `RAG_EVAL_REAL_PROVIDER=1` to run the same golden cases against the configured AI
provider. In that mode latency p95 becomes meaningful and is asserted via
`RAG_EVAL_MAX_P95_MS` (default 5000).
"""


GOLDEN_CORPUS = [
    IngestInput(
        document_id="doc-account",
        document_name="Account Guide",
        file_type="md",
        markdown=(
            "# Reset password\n"
            "Vao Cai dat > Bao mat de dat lai mat khau. "
            "Lien ket dat lai mat khau het han sau 15 phut.\n"
        ),
        source_uri="s3://knowledge/account.md",
        artifact_uri="artifact://doc-account",
    ),
    IngestInput(
        document_id="doc-hr",
        document_name="HR Guide",
        file_type="md",
        markdown=(
            "# Leave policy\n"
            "Nhan vien full-time co 12 ngay nghi phep nam. "
            "Quan ly phe duyet tren he thong HR.\n"
        ),
        source_uri="s3://knowledge/hr.md",
        artifact_uri="artifact://doc-hr",
    ),
    IngestInput(
        document_id="doc-finance",
        document_name="Finance Guide",
        file_type="md",
        markdown=(
            "# Expense reimbursement\n"
            "Chi phi cong tac can nop hoa don trong 30 ngay de duoc hoan ung.\n"
        ),
        source_uri="s3://knowledge/finance.md",
        artifact_uri="artifact://doc-finance",
    ),
]

GOLDEN_QUERIES = [
    {
        "query": "reset mat khau het han bao lau",
        "document_id": "doc-account",
        "source_uri": "s3://knowledge/account.md",
        "artifact_uri": "artifact://doc-account",
    },
    {
        "query": "nhan vien co bao nhieu ngay nghi phep nam",
        "document_id": "doc-hr",
        "source_uri": "s3://knowledge/hr.md",
        "artifact_uri": "artifact://doc-hr",
    },
    {
        "query": "nop hoa don cong tac trong bao nhieu ngay",
        "document_id": "doc-finance",
        "source_uri": "s3://knowledge/finance.md",
        "artifact_uri": "artifact://doc-finance",
    },
]


def _build_eval_engine():
    if os.getenv("RAG_EVAL_REAL_PROVIDER", "").strip() == "1":
        reset_ai_provider()
        return build_engine(provider=get_ai_provider(), caption=True), True
    return build_engine(provider=OfflineProvider(256), caption=True), False


@pytest.mark.asyncio
async def test_golden_queries_preserve_lineage_and_recall() -> None:
    engine, real_provider = _build_eval_engine()
    for document in GOLDEN_CORPUS:
        await engine.ingest(document)

    latencies_ms: list[float] = []
    for case in GOLDEN_QUERIES:
        started = perf_counter()
        results = await engine.search(
            case["query"],
            top_k=3,
            rerank_threshold=0.0,
            correlation_id=f"eval:{case['document_id']}",
        )
        latencies_ms.append((perf_counter() - started) * 1000)

        assert results, f"expected at least one hit for query={case['query']!r}"
        top = results[0]
        assert top.document_id == case["document_id"]
        assert top.lineage.source_uri == case["source_uri"]
        assert top.lineage.artifact_uri == case["artifact_uri"]
        assert top.correlation_id == f"eval:{case['document_id']}"
        assert top.content

    if real_provider:
        p95_ms = quantiles(latencies_ms, n=20, method="inclusive")[-1]
        max_p95_ms = float(os.getenv("RAG_EVAL_MAX_P95_MS", "5000"))
        assert p95_ms < max_p95_ms, (
            f"search p95 too high for golden set: {p95_ms:.1f}ms >= {max_p95_ms:.1f}ms"
        )


@pytest.mark.asyncio
async def test_golden_queries_no_answer_policy_for_ungrounded_question() -> None:
    engine, _ = _build_eval_engine()
    for document in GOLDEN_CORPUS:
        await engine.ingest(document)

    results = await engine.search(
        "muc dong bao hiem suc khoe hang thang la bao nhieu",
        top_k=3,
        rerank_threshold=1.01,
        correlation_id="eval:no-answer",
    )

    assert results == []
