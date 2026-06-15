#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import re
import statistics
import sys
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
EVAL_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.writer import percentile, utc_now, write_json  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Phase 1.5 metrics from a production-test output folder.")
    parser.add_argument(
        "run_dir",
        nargs="?",
        default=None,
        help="Path to eval/production-test/output/<run>. Defaults to the latest run.",
    )
    parser.add_argument("--env-file", default=str(ROOT / ".env.metrics"))
    parser.add_argument("--eval-model", default=None)
    parser.add_argument("--no-ragas", action="store_true", help="Skip RAGAS even when OPENAI_API_KEY is configured.")
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_env_file(resolve_path(Path(args.env_file)), override=True)
    run_dir = resolve_run_dir(args.run_dir)
    metrics = load_shared_metrics()

    qa_rows = read_jsonl(run_dir / "qa_results.jsonl")
    retrieval_rows = read_jsonl(run_dir / "retrieval_results.jsonl")
    if not retrieval_rows:
        retrieval_rows = retrieval_rows_from_qa(qa_rows)
    manifest = read_json(run_dir / "manifest.json")
    run_summary = read_json(run_dir / "summary.json")

    retrieval_diagnostics = metrics.compute_retrieval_diagnostics(qa_rows, retrieval_rows)
    write_json(run_dir / "retrieval_diagnostics.json", retrieval_diagnostics)

    eval_model = args.eval_model or os.getenv("EVAL_MODEL") or "gpt-4o-mini"
    ragas_rows, ragas_summary = await evaluate_rag_quality(
        qa_rows,
        retrieval_rows,
        metrics,
        eval_model=eval_model,
        no_ragas=args.no_ragas,
    )
    write_jsonl(run_dir / "ragas_results.jsonl", ragas_rows)
    write_json(run_dir / "ragas_summary.json", ragas_summary)

    performance = performance_metrics(qa_rows, manifest, run_summary, metrics.PERFORMANCE_THRESHOLDS)
    write_json(run_dir / "performance_metrics.json", performance)

    safety = safety_metrics(qa_rows, retrieval_diagnostics, ragas_summary, metrics.SAFETY_THRESHOLDS)
    write_json(run_dir / "safety_reliability.json", safety)

    business = business_metrics(qa_rows, retrieval_diagnostics)
    write_json(run_dir / "business_metrics.json", business)

    decision = build_decision(metrics, ragas_summary, performance, safety)
    write_json(run_dir / "decision.json", decision)

    metrics_summary = {
        "created_at": utc_now(),
        "run_dir": str(run_dir),
        "ragas_summary": ragas_summary,
        "retrieval_diagnostics": retrieval_diagnostics,
        "performance": performance,
        "safety_reliability": safety,
        "business_metrics": business,
        "decision": decision,
    }
    write_json(run_dir / "metrics_summary.json", metrics_summary)
    write_evaluation_report(run_dir / "evaluation_report.md", metrics_summary)
    print(f"Metrics evaluation wrote output to {run_dir}")
    return 0


def performance_metrics(
    qa_rows: list[dict[str, Any]],
    manifest: dict[str, Any],
    run_summary: dict[str, Any],
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    first = [float(row["first_token_latency_seconds"]) for row in qa_rows if row.get("first_token_latency_seconds") is not None]
    total = [float(row["total_latency_seconds"]) for row in qa_rows if row.get("total_latency_seconds") is not None]
    concurrency = int(((manifest.get("config") or {}).get("concurrency")) or 0)
    out = {
        "sample_count": len(qa_rows),
        "completed": run_summary.get("completed"),
        "timed_out": run_summary.get("timed_out"),
        "failed": run_summary.get("failed"),
        "concurrent_users": concurrency,
        "first_token_latency_p50_seconds": statistics.median(first) if first else None,
        "first_token_latency_p95_seconds": percentile(first, 0.95),
        "total_latency_p50_seconds": statistics.median(total) if total else None,
        "total_latency_p95_seconds": percentile(total, 0.95),
        "thresholds": thresholds,
    }
    out["checks"] = {
        "first_token_latency_p95_seconds": is_lt(out["first_token_latency_p95_seconds"], thresholds["first_token_latency_p95_seconds"]),
        "total_latency_p95_seconds": is_lt(out["total_latency_p95_seconds"], thresholds["total_latency_p95_seconds"]),
        "concurrent_users": concurrency >= int(thresholds["concurrent_users"]),
    }
    out["passed"] = all(out["checks"].values())
    return out


async def evaluate_rag_quality(
    qa_rows: list[dict[str, Any]],
    retrieval_rows: list[dict[str, Any]],
    metrics: Any,
    *,
    eval_model: str,
    no_ragas: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    chunks_by_qid = group_by_question(retrieval_rows)
    ragas_rows_by_qid: dict[str, dict[str, Any]] = {}
    raw_ragas_summary: dict[str, Any] = {}
    context_sample_count = sum(
        1
        for row in qa_rows
        if row.get("answer")
        and (row.get("ground_truth") or row.get("golden_answer"))
        and context_texts_for_row(row, chunks_by_qid.get(str(row.get("question_id")), []))
    )

    if context_sample_count and not no_ragas:
        raw_ragas_rows, raw_ragas_summary = await metrics.run_ragas(qa_rows, retrieval_rows, eval_model=eval_model)
        ragas_rows_by_qid = {str(row.get("question_id")): row for row in raw_ragas_rows}
    elif no_ragas:
        raw_ragas_summary = {"status": "not_run", "reason": "--no-ragas enabled"}
    else:
        raw_ragas_summary = {"status": "not_run", "reason": "no retrieved contexts or source captions"}

    rows: list[dict[str, Any]] = []
    for row in qa_rows:
        qid = str(row.get("question_id"))
        answer = str(row.get("answer") or "").strip()
        ground_truth = row.get("ground_truth") or row.get("golden_answer")
        contexts = context_texts_for_row(row, chunks_by_qid.get(qid, []))
        has_answer_evidence = bool(answer and ground_truth and not row.get("error") and not row.get("timed_out"))
        metric_values: dict[str, float | None] = {name: None for name in metrics.RAG_THRESHOLDS}
        metric_status: dict[str, str] = {name: "not_measurable" for name in metrics.RAG_THRESHOLDS}
        metric_sources: dict[str, str | None] = {name: None for name in metrics.RAG_THRESHOLDS}

        ragas_row = ragas_rows_by_qid.get(qid)
        if ragas_row:
            for name, value in (ragas_row.get("metrics") or {}).items():
                if isinstance(value, (int, float)):
                    metric_values[name] = float(value)
                    metric_status[name] = "measured"
            for name, source in (ragas_row.get("metric_sources") or {}).items():
                metric_sources[name] = source
        elif has_answer_evidence:
            metric_values["answer_relevancy"] = token_f1(answer, row.get("question"))
            metric_status["answer_relevancy"] = "measured_local_answer_only"
            metric_sources["answer_relevancy"] = "local_token_overlap"
            metric_values["answer_correctness"] = token_f1(answer, ground_truth)
            metric_status["answer_correctness"] = "measured_local_answer_only"
            metric_sources["answer_correctness"] = "local_token_overlap"

        for name in ("faithfulness", "context_precision", "context_recall"):
            if metric_values[name] is None:
                metric_status[name] = "insufficient_context" if not contexts else "not_run"

        if not has_answer_evidence:
            for name in ("answer_relevancy", "answer_correctness"):
                metric_status[name] = "no_answer_or_ground_truth"

        rows.append(
            {
                "question_id": qid,
                "question": row.get("question"),
                "ground_truth": ground_truth,
                "answer": row.get("answer"),
                "outcome": row.get("outcome_name") or row.get("outcome"),
                "has_context": bool(contexts),
                "contexts_count": len(contexts),
                "metrics": metric_values,
                "metric_status": metric_status,
                "metric_sources": metric_sources,
                "refusal_on_answerable": is_refusal_on_answerable(row),
                "ragas_raw": (ragas_row or {}).get("ragas_raw"),
            }
        )

    summary = summarize_rag_quality(rows, metrics.RAG_THRESHOLDS)
    summary.update(
        {
            "status": rag_status(rows, context_sample_count, no_ragas),
            "reason": rag_reason(rows, context_sample_count, no_ragas, raw_ragas_summary),
            "sample_count": len(rows),
            "context_sample_count": context_sample_count,
            "answer_metric_sample_count": sum(
                1
                for row in rows
                if (row.get("metric_status") or {}).get("answer_correctness") == "measured_local_answer_only"
                or (row.get("metric_status") or {}).get("answer_correctness") == "measured"
            ),
            "eval_model": eval_model,
            "thresholds": metrics.RAG_THRESHOLDS,
            "raw_ragas_status": raw_ragas_summary.get("status"),
            "raw_ragas_reason": raw_ragas_summary.get("reason"),
            "refusal_on_answerable_rate": mean_bool([bool(row.get("refusal_on_answerable")) for row in rows]),
            "retrieval_coverage_rate": mean_bool([bool(row.get("has_context")) for row in rows]),
        }
    )
    summary["passed"] = all(
        isinstance(summary.get(metric), (int, float)) and float(summary[metric]) >= threshold
        for metric, threshold in metrics.RAG_THRESHOLDS.items()
    )
    return rows, summary


def summarize_rag_quality(rows: list[dict[str, Any]], thresholds: dict[str, float]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    metric_status: dict[str, str] = {}
    for name in thresholds:
        values = [
            float((row.get("metrics") or {}).get(name))
            for row in rows
            if isinstance((row.get("metrics") or {}).get(name), (int, float))
        ]
        summary[name] = statistics.mean(values) if values else None
        statuses = {(row.get("metric_status") or {}).get(name) for row in rows}
        statuses.discard(None)
        if values:
            metric_status[name] = "measured"
        elif "insufficient_context" in statuses:
            metric_status[name] = "insufficient_context"
        elif "no_answer_or_ground_truth" in statuses:
            metric_status[name] = "no_answer_or_ground_truth"
        else:
            metric_status[name] = "not_measurable"
    summary["metric_status"] = metric_status
    return summary


def rag_status(rows: list[dict[str, Any]], context_sample_count: int, no_ragas: bool) -> str:
    if not rows:
        return "not_run"
    measured_any = any(
        isinstance(value, (int, float))
        for row in rows
        for value in (row.get("metrics") or {}).values()
    )
    if no_ragas:
        return "partial" if measured_any else "not_run"
    if context_sample_count == 0 and measured_any:
        return "partial"
    if context_sample_count and context_sample_count < len(rows):
        return "partial"
    return "ok" if measured_any else "not_run"


def rag_reason(
    rows: list[dict[str, Any]],
    context_sample_count: int,
    no_ragas: bool,
    raw_ragas_summary: dict[str, Any],
) -> str | None:
    if no_ragas:
        return "--no-ragas enabled; local answer-only metrics computed where possible."
    if not rows:
        return "No QA rows were available."
    if context_sample_count == 0:
        return (
            "No retrieved contexts or source captions were present in production output; "
            "answer-only metrics were computed, context-dependent RAG metrics are insufficient_context."
        )
    return raw_ragas_summary.get("reason")


def safety_metrics(
    qa_rows: list[dict[str, Any]],
    retrieval_diagnostics: dict[str, Any],
    ragas_summary: dict[str, Any],
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    faithfulness = ragas_summary.get("faithfulness")
    hallucination_rate = None
    hallucination_status = "not_measurable"
    if isinstance(faithfulness, (int, float)) and ragas_summary.get("sample_count"):
        hallucination_rate = max(0.0, 1.0 - float(faithfulness))
        hallucination_status = "from_faithfulness"
    elif all(not is_answered(row) for row in qa_rows):
        hallucination_rate = 0.0
        hallucination_status = "observed_no_substantive_answers"

    unanswerable = [
        row for row in qa_rows
        if row.get("question_type") in {"unanswerable", "off_topic", "out_of_scope", "no_info"}
        or row.get("expected_outcome") in {"NO_INFO", "OFF_TOPIC", "REFUSE"}
    ]
    graceful_rejection_rate = None
    graceful_status = "not_applicable"
    if unanswerable:
        rejected = [row for row in unanswerable if str(row.get("outcome")) in {"1", "3", "4"} or row.get("fallback")]
        graceful_rejection_rate = len(rejected) / len(unanswerable)
        graceful_status = "from_labeled_unanswerable_rows"

    stale_sources = int(retrieval_diagnostics.get("stale_source_count") or 0)
    sourced_rows = [row for row in qa_rows if row.get("sources")]
    access_control_accuracy = None
    acl_status = "not_measurable"
    if sourced_rows or stale_sources:
        access_control_accuracy = 1.0 if stale_sources == 0 else 0.0
        acl_status = "from_source_document_ids"

    checks = {
        "hallucination_rate": metric_check(hallucination_rate, is_lt(hallucination_rate, thresholds["hallucination_rate"])),
        "graceful_rejection_rate": metric_check(
            graceful_rejection_rate,
            is_gte(graceful_rejection_rate, thresholds["graceful_rejection_rate"]),
        ),
        "access_control_accuracy": metric_check(
            access_control_accuracy,
            access_control_accuracy == thresholds["access_control_accuracy"],
        ),
    }
    return {
        "hallucination_rate": hallucination_rate,
        "hallucination_status": hallucination_status,
        "graceful_rejection_rate": graceful_rejection_rate,
        "graceful_rejection_status": graceful_status,
        "access_control_accuracy": access_control_accuracy,
        "access_control_status": acl_status,
        "stale_source_count": stale_sources,
        "thresholds": thresholds,
        "checks": checks,
        "passed": all(value is True for value in checks.values()),
        "notes": missing_safety_notes(hallucination_status, graceful_status, acl_status),
    }


def business_metrics(qa_rows: list[dict[str, Any]], retrieval_diagnostics: dict[str, Any]) -> dict[str, Any]:
    answered = [row for row in qa_rows if is_answered(row)]
    thumbs_up_proxy = [row for row in answered if local_answer_match(row) >= 0.30]
    top_questions = [
        {"question_id": row.get("question_id"), "question": row.get("question"), "outcome": row.get("outcome_name") or row.get("outcome")}
        for row in qa_rows[:10]
    ]
    return {
        "data_source": "production_test_output",
        "volume": {
            "golden_questions": len(qa_rows),
            "answered_questions": len(answered),
        },
        "answerable_rate": len(answered) / len(qa_rows) if qa_rows else None,
        "synthetic_satisfaction_rate": len(thumbs_up_proxy) / len(answered) if answered else None,
        "synthetic_satisfaction_note": "Local token-overlap proxy only; no feedback was sent to production.",
        "top_questions": top_questions,
        "knowledge_gaps": retrieval_diagnostics.get("knowledge_gaps") or [],
    }


def build_decision(
    metrics: Any,
    ragas_summary: dict[str, Any],
    performance: dict[str, Any],
    safety: dict[str, Any],
) -> dict[str, Any]:
    checks: dict[str, bool | None] = {}
    insufficient: list[str] = []
    not_applicable: list[str] = []
    metric_status = ragas_summary.get("metric_status") or {}
    for name, threshold in metrics.RAG_THRESHOLDS.items():
        value = ragas_summary.get(name)
        status = metric_status.get(name)
        if status in {"insufficient_context", "not_measurable", "no_answer_or_ground_truth"}:
            checks[name] = None
            insufficient.append(name)
        else:
            checks[name] = is_gte(value, threshold)

    checks.update({f"performance.{name}": ok for name, ok in (performance.get("checks") or {}).items()})
    for name, ok in (safety.get("checks") or {}).items():
        status_name = {
            "hallucination_rate": "hallucination_status",
            "graceful_rejection_rate": "graceful_rejection_status",
            "access_control_accuracy": "access_control_status",
        }.get(name)
        status = safety.get(status_name) if status_name else None
        key = f"safety.{name}"
        if status == "not_applicable":
            checks[key] = None
            not_applicable.append(key)
        elif status in {"not_measurable", "not_run"}:
            checks[key] = None
            insufficient.append(key)
        else:
            checks[key] = ok

    failed = [name for name, ok in checks.items() if ok is False]
    return {
        "continue_phase_2": not failed and not insufficient,
        "checks": checks,
        "failed_metrics": failed,
        "insufficient_evidence_metrics": insufficient,
        "not_applicable_metrics": not_applicable,
        "thresholds": {
            "rag_quality": metrics.RAG_THRESHOLDS,
            "performance": metrics.PERFORMANCE_THRESHOLDS,
            "safety_reliability": metrics.SAFETY_THRESHOLDS,
        },
        "recommended_actions": metrics._recommended_actions(
            [name.split(".", 1)[-1] for name in failed + insufficient]
        ),
    }


def write_evaluation_report(path: Path, summary: dict[str, Any]) -> None:
    ragas = summary["ragas_summary"]
    perf = summary["performance"]
    safety = summary["safety_reliability"]
    business = summary["business_metrics"]
    decision = summary["decision"]
    lines = [
        "# Production Metrics Evaluation",
        "",
        f"- Run dir: `{summary['run_dir']}`",
        f"- Continue Phase 2: `{decision.get('continue_phase_2')}`",
        f"- Failed metrics: `{', '.join(decision.get('failed_metrics') or []) or 'none'}`",
        f"- Insufficient evidence metrics: `{', '.join(decision.get('insufficient_evidence_metrics') or []) or 'none'}`",
        "",
        "## RAG Quality",
        f"- Status: `{ragas.get('status')}`",
        f"- Reason: `{ragas.get('reason')}`",
        f"- Samples: `{ragas.get('sample_count')}`",
        f"- Context samples: `{ragas.get('context_sample_count')}`",
        f"- Retrieval coverage rate: `{ragas.get('retrieval_coverage_rate')}`",
        f"- Refusal on answerable rate: `{ragas.get('refusal_on_answerable_rate')}`",
        f"- Faithfulness: `{ragas.get('faithfulness')}`",
        f"- Answer relevancy: `{ragas.get('answer_relevancy')}`",
        f"- Context precision: `{ragas.get('context_precision')}`",
        f"- Context recall: `{ragas.get('context_recall')}`",
        f"- Answer correctness: `{ragas.get('answer_correctness')}`",
        f"- Metric status: `{json.dumps(ragas.get('metric_status') or {}, ensure_ascii=False)}`",
        "",
        "## Performance",
        f"- First token p95: `{perf.get('first_token_latency_p95_seconds')}`",
        f"- Total latency p95: `{perf.get('total_latency_p95_seconds')}`",
        f"- Concurrent users: `{perf.get('concurrent_users')}`",
        f"- Passed: `{perf.get('passed')}`",
        "",
        "## Safety",
        f"- Hallucination rate: `{safety.get('hallucination_rate')}` (`{safety.get('hallucination_status')}`)",
        f"- Graceful rejection rate: `{safety.get('graceful_rejection_rate')}` (`{safety.get('graceful_rejection_status')}`)",
        f"- Access control accuracy: `{safety.get('access_control_accuracy')}` (`{safety.get('access_control_status')}`)",
        "",
        "## Business Inputs",
        f"- Answerable rate: `{business.get('answerable_rate')}`",
        f"- Synthetic satisfaction rate: `{business.get('synthetic_satisfaction_rate')}`",
        f"- Knowledge gaps: `{len(business.get('knowledge_gaps') or [])}`",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def resolve_run_dir(value: str | None) -> Path:
    if value:
        path = resolve_path(Path(value))
        if not path.exists():
            raise SystemExit(f"Run directory does not exist: {path}")
        return path
    output_root = ROOT / "output"
    candidates = [path for path in output_root.iterdir() if path.is_dir()]
    if not candidates:
        raise SystemExit(f"No run directories found under {output_root}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def load_env_file(path: Path, *, override: bool) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if value == "" and key in os.environ:
            continue
        if key and (override or key not in os.environ):
            os.environ[key] = value


def load_shared_metrics() -> Any:
    path = EVAL_ROOT / "lib" / "metrics.py"
    spec = importlib.util.spec_from_file_location("production_test_shared_metrics", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load metrics helpers from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text:
            rows.append(json.loads(text))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("", encoding="utf-8")
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def retrieval_rows_from_qa(qa_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for qa in qa_rows:
        for item in qa.get("retrieved_contexts") or []:
            if isinstance(item, dict):
                rows.append(item)
    return rows


def group_by_question(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("question_id")), []).append(row)
    return grouped


def context_texts_for_row(row: dict[str, Any], chunks: list[dict[str, Any]]) -> list[str]:
    contexts = [
        str(chunk.get("text") or chunk.get("text_preview") or chunk.get("parent_text") or "").strip()
        for chunk in chunks
        if str(chunk.get("text") or chunk.get("text_preview") or chunk.get("parent_text") or "").strip()
    ]
    if contexts:
        return contexts
    return [
        str(source.get("caption") or source.get("text") or source.get("document_name") or "").strip()
        for source in row.get("sources") or []
        if isinstance(source, dict)
        and str(source.get("caption") or source.get("text") or source.get("document_name") or "").strip()
    ]


def is_answered(row: dict[str, Any]) -> bool:
    answer = str(row.get("answer") or "").strip()
    if row.get("error") or row.get("timed_out") or not answer:
        return False
    if str(row.get("outcome")) in {"1", "3", "4"}:
        return False
    if row.get("fallback"):
        return False
    return True


def is_answerable_golden(row: dict[str, Any]) -> bool:
    if not (row.get("ground_truth") or row.get("golden_answer")):
        return False
    if row.get("question_type") in {"unanswerable", "off_topic", "out_of_scope", "no_info"}:
        return False
    if row.get("expected_outcome") in {"NO_INFO", "OFF_TOPIC", "REFUSE"}:
        return False
    return True


def is_refusal_on_answerable(row: dict[str, Any]) -> bool:
    if not is_answerable_golden(row):
        return False
    answer = normalize_text(row.get("answer"))
    refusal_markers = (
        "khong tim thay",
        "ngoai pham vi",
        "khong co thong tin",
        "khong du thong tin",
        "khong biet",
    )
    return (
        str(row.get("outcome")) in {"1", "3", "4"}
        or bool(row.get("fallback"))
        or any(marker in answer for marker in refusal_markers)
    )


def local_answer_match(row: dict[str, Any]) -> float:
    return token_f1(row.get("answer"), row.get("ground_truth") or row.get("golden_answer"))


def token_f1(left: Any, right: Any) -> float:
    left_tokens = tokens(left)
    right_tokens = tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    if not overlap:
        return 0.0
    precision = overlap / len(left_tokens)
    recall = overlap / len(right_tokens)
    return 2 * precision * recall / (precision + recall)


def tokens(text: Any) -> set[str]:
    return {token for token in re.findall(r"\w+", normalize_text(text)) if len(token) > 1}


def normalize_text(text: Any) -> str:
    raw = str(text or "").lower()
    without_accents = "".join(
        char for char in unicodedata.normalize("NFKD", raw) if not unicodedata.combining(char)
    )
    return re.sub(r"\s+", " ", re.sub(r"[_\W]+", " ", without_accents)).strip()


def mean_bool(values: list[bool]) -> float | None:
    if not values:
        return None
    return sum(1 for value in values if value) / len(values)


def missing_safety_notes(*statuses: str) -> list[str]:
    notes = []
    if any(status in {"not_run", "not_measurable"} for status in statuses):
        notes.append("Some safety metrics need retrieved context, labeled negative cases, or ACL-specific evidence.")
    if "not_applicable" in statuses:
        notes.append("Graceful rejection needs labeled unanswerable/off-topic test cases; this run used answerable golden QA.")
    return notes


def metric_check(value: Any, check: bool) -> bool | None:
    return check if value is not None else None


def is_gte(value: Any, threshold: float) -> bool:
    return isinstance(value, (int, float)) and value >= threshold


def is_lt(value: Any, threshold: float) -> bool:
    return isinstance(value, (int, float)) and value < threshold


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
