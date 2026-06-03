from __future__ import annotations

from statistics import quantiles
from time import perf_counter

import pytest

from haystack_interface import IngestInput, OfflineProvider, build_engine


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


@pytest.mark.asyncio
async def test_golden_queries_preserve_lineage_and_recall() -> None:
    engine = build_engine(provider=OfflineProvider(256), caption=True)
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

    p95_ms = quantiles(latencies_ms, n=20, method="inclusive")[-1]
    assert p95_ms < 1000, f"search p95 too high for golden set: {p95_ms:.1f}ms"


@pytest.mark.asyncio
async def test_golden_queries_no_answer_policy_for_ungrounded_question() -> None:
    engine = build_engine(provider=OfflineProvider(256), caption=True)
    for document in GOLDEN_CORPUS:
        await engine.ingest(document)

    results = await engine.search(
        "muc dong bao hiem suc khoe hang thang la bao nhieu",
        top_k=3,
        rerank_threshold=1.01,
        correlation_id="eval:no-answer",
    )

    assert results == []
