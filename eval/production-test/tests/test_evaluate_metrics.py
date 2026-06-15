from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluate_metrics import business_metrics, evaluate_rag_quality, performance_metrics, safety_metrics


def test_performance_metrics_uses_phase_1_5_threshold_names() -> None:
    rows = [
        {"first_token_latency_seconds": 1.0, "total_latency_seconds": 2.0},
        {"first_token_latency_seconds": 3.0, "total_latency_seconds": 4.0},
    ]
    manifest = {"config": {"concurrency": 5}}
    summary = {"completed": 2, "timed_out": 0, "failed": 0}
    thresholds = {
        "first_token_latency_p95_seconds": 2.0,
        "total_latency_p95_seconds": 8.0,
        "concurrent_users": 50,
    }

    result = performance_metrics(rows, manifest, summary, thresholds)

    assert result["sample_count"] == 2
    assert result["concurrent_users"] == 5
    assert set(result["checks"]) == {
        "first_token_latency_p95_seconds",
        "total_latency_p95_seconds",
        "concurrent_users",
    }


def test_business_metrics_marks_rejected_rows_unanswered() -> None:
    rows = [
        {"answer": "not in scope", "outcome": 4, "question_id": "q1", "question": "Q1"},
        {"answer": "answer", "outcome": 5, "question_id": "q2", "question": "Q2", "ground_truth": "answer"},
    ]
    result = business_metrics(rows, {"knowledge_gaps": [{"question_id": "q1"}]})

    assert result["volume"]["golden_questions"] == 2
    assert result["volume"]["answered_questions"] == 1
    assert result["answerable_rate"] == 0.5
    assert len(result["knowledge_gaps"]) == 1


async def _should_not_call_ragas(*args, **kwargs):  # noqa: ANN002, ANN003
    raise AssertionError("RAGAS should not run when no contexts are available")


def test_rag_quality_no_context_computes_answer_only_metrics() -> None:
    rows = [
        {
            "question_id": "q1",
            "question": "FMLA eligibility?",
            "answer": "Mình không tìm thấy thông tin này trong tài liệu.",
            "golden_answer": "Employees are eligible after required service and hours.",
            "outcome": 3,
        }
    ]
    metrics = SimpleNamespace(
        RAG_THRESHOLDS={
            "faithfulness": 0.9,
            "answer_relevancy": 0.85,
            "context_precision": 0.8,
            "context_recall": 0.8,
            "answer_correctness": 0.8,
        },
        run_ragas=_should_not_call_ragas,
    )

    ragas_rows, summary = __import__("asyncio").run(
        evaluate_rag_quality(rows, [], metrics, eval_model="test-model", no_ragas=False)
    )

    assert summary["status"] == "partial"
    assert summary["sample_count"] == 1
    assert summary["context_sample_count"] == 0
    assert summary["retrieval_coverage_rate"] == 0.0
    assert summary["refusal_on_answerable_rate"] == 1.0
    assert summary["metric_status"]["faithfulness"] == "insufficient_context"
    assert summary["metric_status"]["answer_correctness"] == "measured"
    assert ragas_rows[0]["metric_status"]["answer_correctness"] == "measured_local_answer_only"
    assert ragas_rows[0]["metrics"]["context_precision"] is None


def test_safety_metrics_marks_unavailable_acl_as_not_measurable() -> None:
    rows = [{"answer": "Mình không tìm thấy thông tin này.", "outcome": 3}]
    thresholds = {
        "hallucination_rate": 0.05,
        "graceful_rejection_rate": 0.95,
        "access_control_accuracy": 1.0,
    }

    result = safety_metrics(rows, {"stale_source_count": 0}, {"faithfulness": None, "sample_count": 1}, thresholds)

    assert result["hallucination_status"] == "observed_no_substantive_answers"
    assert result["graceful_rejection_status"] == "not_applicable"
    assert result["access_control_status"] == "not_measurable"
    assert result["checks"]["access_control_accuracy"] is None
