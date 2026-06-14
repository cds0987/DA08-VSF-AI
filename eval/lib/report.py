from __future__ import annotations

from pathlib import Path
from typing import Any


def write_report(
    path: Path,
    *,
    dataset_name: str,
    ragas_summary: dict[str, Any],
    retrieval_diagnostics: dict[str, Any],
    performance_cold: dict[str, Any],
    performance_warm: dict[str, Any] | None,
    safety: dict[str, Any],
    business: dict[str, Any],
    decision: dict[str, Any],
) -> None:
    thresholds = decision.get("thresholds") or {}
    lines = [
        f"# Phase 1.5 Evaluation Report: {dataset_name}",
        "",
        f"Decision: **{'CONTINUE PHASE 2' if decision.get('continue_phase_2') else 'TUNE BEFORE PHASE 2'}**",
        "",
        "## RAG Quality",
        "",
        _metric_line("Faithfulness", ragas_summary.get("faithfulness"), ">=", thresholds["rag_quality"]["faithfulness"]),
        _metric_line("Answer relevancy", ragas_summary.get("answer_relevancy"), ">=", thresholds["rag_quality"]["answer_relevancy"]),
        _metric_line("Context precision", ragas_summary.get("context_precision"), ">=", thresholds["rag_quality"]["context_precision"]),
        _metric_line("Context recall", ragas_summary.get("context_recall"), ">=", thresholds["rag_quality"]["context_recall"]),
        _metric_line("Answer correctness", ragas_summary.get("answer_correctness"), ">=", thresholds["rag_quality"]["answer_correctness"]),
        f"- RAGAS status: `{ragas_summary.get('status')}`",
        f"- RAGAS sample count: `{ragas_summary.get('sample_count')}`",
        "",
        "## Retrieval Diagnostic",
        "",
        f"- Document hit@k: `{_fmt(retrieval_diagnostics.get('document_hit_at_k'))}`",
        f"- Expected chunk hit@k: `{_fmt(retrieval_diagnostics.get('expected_chunk_hit_at_k'))}`",
        f"- Stale source count: `{retrieval_diagnostics.get('stale_source_count', 0)}`",
        f"- Page hit@k: `{_fmt(retrieval_diagnostics.get('page_hit_at_k'))}`",
        f"- Average retrieval score: `{_fmt(retrieval_diagnostics.get('average_retrieval_score'))}`",
        f"- Knowledge gaps: `{retrieval_diagnostics.get('low_score_question_count')}`",
        "",
        "## Performance",
        "",
        _metric_line(
            "Cold first token latency p95 seconds",
            performance_cold.get("first_token_latency_p95_seconds"),
            "<",
            thresholds["performance"]["first_token_latency_p95_seconds"],
        ),
        _metric_line(
            "Cold total latency p95 seconds",
            performance_cold.get("total_latency_p95_seconds"),
            "<",
            thresholds["performance"]["total_latency_p95_seconds"],
        ),
        _metric_line(
            "Cold concurrent users",
            performance_cold.get("concurrent_users"),
            ">=",
            thresholds["performance"]["concurrent_users"],
        ),
        f"- Cold error rate: `{_fmt(performance_cold.get('error_rate'))}`",
        f"- Cold requests/sec: `{_fmt(performance_cold.get('requests_per_second'))}`",
        f"- Cold cache hit count: `{performance_cold.get('cache_hit_count')}`",
        "",
    ]
    if performance_warm:
        lines.extend(
            [
                "## Performance Warm",
                "",
                f"- Warm status: `{performance_warm.get('status')}`",
                f"- Warm first token p95 seconds: `{_fmt(performance_warm.get('first_token_latency_p95_seconds'))}`",
                f"- Warm total latency p95 seconds: `{_fmt(performance_warm.get('total_latency_p95_seconds'))}`",
                f"- Warm cache hit count: `{performance_warm.get('cache_hit_count')}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Safety & Reliability",
            "",
            _metric_line("Hallucination rate", safety.get("hallucination_rate"), "<", thresholds["safety_reliability"]["hallucination_rate"]),
            _metric_line(
                "Graceful rejection rate",
                safety.get("graceful_rejection_rate"),
                ">=",
                thresholds["safety_reliability"]["graceful_rejection_rate"],
            ),
            _metric_line(
                "Access control accuracy",
                safety.get("access_control_accuracy"),
                "==",
                thresholds["safety_reliability"]["access_control_accuracy"],
            ),
            "",
            "## Business Metrics",
            "",
            f"- Data source: `{business.get('data_source')}`",
            f"- Volume: `{business.get('volume')}`",
            f"- Feedback rate: `{_fmt(business.get('feedback_rate'))}`",
            f"- Knowledge gaps: `{len(business.get('knowledge_gaps') or [])}`",
            "",
            "## Decision",
            "",
            f"- Continue Phase 2: `{decision.get('continue_phase_2')}`",
            f"- Failed metrics: `{', '.join(decision.get('failed_metrics') or []) or 'none'}`",
            "",
        ]
    )
    actions = decision.get("recommended_actions") or []
    if actions:
        lines.append("Recommended actions:")
        for action in actions:
            lines.append(f"- {action}")
        lines.append("")
    reason = ragas_summary.get("reason")
    if reason:
        lines.extend(["Notes:", f"- RAGAS reason: {reason}", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _metric_line(label: str, value: Any, op: str, threshold: Any) -> str:
    passed = _passes(value, op, threshold)
    return f"- {label}: `{_fmt(value)}` {op} `{_fmt(threshold)}` -> **{'PASS' if passed else 'FAIL'}**"


def _passes(value: Any, op: str, threshold: Any) -> bool:
    if not isinstance(value, (int, float)) or not isinstance(threshold, (int, float)):
        return False
    if op == ">=":
        return float(value) >= float(threshold)
    if op == "<":
        return float(value) < float(threshold)
    if op == "==":
        return float(value) == float(threshold)
    return False


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            return "n/a"
        return f"{value:.4f}"
    return str(value)
