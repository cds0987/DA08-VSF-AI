from __future__ import annotations

import os
import re
import statistics
import sys
import types
import unicodedata
import asyncio
from typing import Any


RAG_THRESHOLDS = {
    "faithfulness": 0.90,
    "answer_relevancy": 0.85,
    "context_precision": 0.80,
    "context_recall": 0.80,
    "answer_correctness": 0.80,
}

PERFORMANCE_THRESHOLDS = {
    "first_token_latency_p95_seconds": 2.0,
    "total_latency_p95_seconds": 8.0,
    "concurrent_users": 50,
}

SAFETY_THRESHOLDS = {
    "hallucination_rate": 0.05,
    "graceful_rejection_rate": 0.95,
    "access_control_accuracy": 1.0,
}


def compute_retrieval_diagnostics(
    qa_rows: list[dict[str, Any]],
    retrieval_rows: list[dict[str, Any]],
    *,
    low_score_threshold: float = 0.70,
) -> dict[str, Any]:
    chunks_by_qid = _group_by_question(retrieval_rows)
    valid = [row for row in qa_rows if not row.get("skip_reason")]
    doc_hits: list[bool] = []
    chunk_hits: list[bool] = []
    page_hits: list[bool] = []
    scores: list[float] = []
    gaps: list[dict[str, Any]] = []
    stale_source_count = 0
    stale_source_rows: list[dict[str, Any]] = []
    for row in valid:
        qid = str(row.get("question_id"))
        chunks = chunks_by_qid.get(qid, [])
        stale_sources = _stale_sources(row)
        if stale_sources:
            stale_source_count += len(stale_sources)
            stale_source_rows.append(
                {
                    "question_id": row.get("question_id"),
                    "effective_document_ids": row.get("effective_document_ids") or [],
                    "stale_sources": stale_sources,
                }
            )
        doc_hits.append(_document_hit(row, chunks))
        chunk_hit = _expected_chunk_hit(row, chunks)
        if chunk_hit is not None:
            chunk_hits.append(chunk_hit)
        page_hit = _page_hit(row, chunks)
        if page_hit is not None:
            page_hits.append(page_hit)
        chunk_scores = [float(c["score"]) for c in chunks if isinstance(c.get("score"), (int, float))]
        scores.extend(chunk_scores)
        max_score = max(chunk_scores) if chunk_scores else None
        if max_score is None or max_score < low_score_threshold:
            gaps.append(
                {
                    "question_id": row.get("question_id"),
                    "question": row.get("question"),
                    "source_doc": row.get("source_doc") or row.get("doc_id"),
                    "max_score": max_score,
                    "reason": "no_retrieval" if max_score is None else "low_retrieval_score",
                }
            )
    return {
        "valid_question_count": len(valid),
        "skipped_question_count": len(qa_rows) - len(valid),
        "document_hit_at_k": _mean_bool(doc_hits),
        "expected_chunk_hit_at_k": _mean_bool(chunk_hits),
        "page_hit_at_k": _mean_bool(page_hits),
        "average_retrieval_score": statistics.mean(scores) if scores else None,
        "low_score_threshold": low_score_threshold,
        "low_score_question_count": len(gaps),
        "knowledge_gaps": gaps,
        "stale_source_count": stale_source_count,
        "stale_source_rows": stale_source_rows,
    }


def compute_business_metrics(
    qa_rows: list[dict[str, Any]],
    feedback_rows: list[dict[str, Any]],
    retrieval_diagnostics: dict[str, Any],
    admin_metrics: dict[str, Any],
) -> dict[str, Any]:
    answered = [row for row in qa_rows if _is_answered(row)]
    return {
        "data_source": "synthetic_eval",
        "volume": {
            "golden_questions": len(qa_rows),
            "answered_questions": len(answered),
            "feedback_events_sent": len(feedback_rows),
        },
        "feedback_rate": _safe_div(len(feedback_rows), len(answered)),
        "top_questions": (admin_metrics or {}).get("top_questions") or [],
        "knowledge_gaps": retrieval_diagnostics.get("knowledge_gaps") or [],
        "admin_metrics": admin_metrics,
        "feedback_rows": feedback_rows,
    }


def feedback_score_for_row(row: dict[str, Any], retrieval_chunks: list[dict[str, Any]] | None = None) -> int:
    if not _is_answered(row):
        return -1
    if _token_f1(row.get("answer", ""), row.get("ground_truth") or row.get("golden_answer", "")) >= 0.30:
        return 1
    if retrieval_chunks and _document_hit(row, retrieval_chunks):
        return 1
    return -1


async def run_ragas(
    qa_rows: list[dict[str, Any]],
    retrieval_rows: list[dict[str, Any]],
    *,
    eval_model: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    chunks_by_qid = _group_by_question(retrieval_rows)
    samples = _ragas_samples(qa_rows, chunks_by_qid)
    if not samples:
        summary = {
            **{metric: 0.0 for metric in RAG_THRESHOLDS},
            "passed": False,
            "status": "not_run",
            "reason": "no answered samples with ground_truth/context",
            "sample_count": 0,
            "thresholds": RAG_THRESHOLDS,
        }
        return [], summary
    raw_by_qid: dict[str, dict[str, Any]] = {}
    ragas_status = "ok"
    ragas_reason = None
    if not os.getenv("OPENAI_API_KEY"):
        ragas_status = "fallback_only"
        ragas_reason = "OPENAI_API_KEY is not configured"
    else:
        _install_ragas_vertexai_compat()
        try:
            from datasets import Dataset
            from ragas import evaluate
            from ragas.embeddings.base import LangchainEmbeddingsWrapper
            from ragas.llms import LangchainLLMWrapper
            from ragas.metrics import (
                answer_correctness,
                answer_relevancy,
                context_precision,
                context_recall,
                faithfulness,
            )
            from ragas.run_config import RunConfig
            from langchain_openai import ChatOpenAI, OpenAIEmbeddings

            dataset = Dataset.from_list(
                [
                    {
                        "user_input": item["question"],
                        "response": item["answer"],
                        "retrieved_contexts": item["contexts"],
                        "reference": item["ground_truth"],
                    }
                    for item in samples
                ]
            )
            answer_relevancy.strictness = 1
            lc_llm = ChatOpenAI(model=eval_model, temperature=0, n=1)
            ragas_llm = LangchainLLMWrapper(lc_llm, bypass_n=True, bypass_temperature=True)
            lc_embeddings = OpenAIEmbeddings(model=os.getenv("OPENAI_EMBEDDING_MODEL") or "text-embedding-3-small")

            class SyncLangchainEmbeddingsWrapper(LangchainEmbeddingsWrapper):
                async def embed_text(self, text: str, is_async: bool = True) -> list[float]:
                    embeddings = await self.embed_texts([text], is_async=False)
                    return embeddings[0]

                async def embed_texts(self, texts: list[str], is_async: bool = True) -> list[list[float]]:
                    loop = asyncio.get_event_loop()
                    return await loop.run_in_executor(None, self.embed_documents, texts)

                async def aembed_query(self, text: str) -> list[float]:
                    loop = asyncio.get_event_loop()
                    return await loop.run_in_executor(None, self.embed_query, text)

                async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
                    loop = asyncio.get_event_loop()
                    return await loop.run_in_executor(None, self.embed_documents, texts)

            ragas_embeddings = SyncLangchainEmbeddingsWrapper(lc_embeddings)
            result = evaluate(
                dataset,
                metrics=[faithfulness, answer_relevancy, context_precision, context_recall, answer_correctness],
                llm=ragas_llm,
                embeddings=ragas_embeddings,
                run_config=RunConfig(max_workers=1, max_retries=2, timeout=180),
                raise_exceptions=False,
            )
            raw_rows = result.to_pandas().to_dict(orient="records")
            for sample, raw in zip(samples, raw_rows, strict=False):
                raw_by_qid[str(sample["question_id"])] = raw
        except Exception as exc:  # noqa: BLE001
            ragas_status = "fallback_only"
            ragas_reason = f"RAGAS evaluation failed: {exc}"

    rows: list[dict[str, Any]] = []
    for sample in samples:
        qid = str(sample["question_id"])
        raw = raw_by_qid.get(qid) or {}
        fallback = _fallback_ragas_scores(sample, chunks_by_qid.get(qid, []))
        metrics: dict[str, Any] = {}
        sources: dict[str, str] = {}
        for name in RAG_THRESHOLDS:
            value = _metric_value(raw, name)
            if value is None:
                value = fallback[name]
                sources[name] = "fallback_local"
            else:
                sources[name] = "ragas"
            metrics[name] = value
        rows.append(
            {
                "question_id": qid,
                "question": sample["question"],
                "ground_truth": sample["ground_truth"],
                "metrics": metrics,
                "metric_sources": sources,
                "ragas_raw": raw,
            }
        )
    summary = _summarize_ragas(rows)
    summary.update(
        {
            "status": ragas_status,
            "reason": ragas_reason,
            "sample_count": len(rows),
            "eval_model": eval_model,
            "thresholds": RAG_THRESHOLDS,
        }
    )
    return rows, summary


def build_decision(
    *,
    ragas_summary: dict[str, Any],
    performance_cold: dict[str, Any],
    safety: dict[str, Any],
) -> dict[str, Any]:
    checks = {
        "faithfulness": _gte(ragas_summary.get("faithfulness"), RAG_THRESHOLDS["faithfulness"]),
        "answer_relevancy": _gte(ragas_summary.get("answer_relevancy"), RAG_THRESHOLDS["answer_relevancy"]),
        "context_precision": _gte(ragas_summary.get("context_precision"), RAG_THRESHOLDS["context_precision"]),
        "context_recall": _gte(ragas_summary.get("context_recall"), RAG_THRESHOLDS["context_recall"]),
        "answer_correctness": _gte(ragas_summary.get("answer_correctness"), RAG_THRESHOLDS["answer_correctness"]),
        "first_token_latency_p95_seconds": _lt(
            performance_cold.get("first_token_latency_p95_seconds"),
            PERFORMANCE_THRESHOLDS["first_token_latency_p95_seconds"],
        ),
        "total_latency_p95_seconds": _lt(
            performance_cold.get("total_latency_p95_seconds"),
            PERFORMANCE_THRESHOLDS["total_latency_p95_seconds"],
        ),
        "concurrent_users": (performance_cold.get("concurrent_users") or 0) >= PERFORMANCE_THRESHOLDS["concurrent_users"],
        "hallucination_rate": _lt(safety.get("hallucination_rate"), SAFETY_THRESHOLDS["hallucination_rate"]),
        "graceful_rejection_rate": _gte(
            safety.get("graceful_rejection_rate"),
            SAFETY_THRESHOLDS["graceful_rejection_rate"],
        ),
        "access_control_accuracy": safety.get("access_control_accuracy") == SAFETY_THRESHOLDS["access_control_accuracy"],
    }
    failed = [name for name, ok in checks.items() if not ok]
    return {
        "continue_phase_2": not failed,
        "checks": checks,
        "failed_metrics": failed,
        "thresholds": {
            "rag_quality": RAG_THRESHOLDS,
            "performance": PERFORMANCE_THRESHOLDS,
            "safety_reliability": SAFETY_THRESHOLDS,
        },
        "recommended_actions": _recommended_actions(failed),
    }


_CONTEXT_MAX_CHARS = 800

# Patterns (in normalized form) that indicate a chunk contains an LLM meta-response
# rather than real document content — happens when the ingestion pipeline passes an
# empty/invalid chunk to the caption-generation LLM and stores its "please provide
# content" reply verbatim.
_GARBAGE_CONTEXT_PATTERNS = (
    "xin vui long cung cap noi dung",
    "please provide",
    "provide the content",
    "de toi co the tom tat",
    "xin cung cap noi dung",
    "vui long cung cap",
)


def _is_garbage_context(text: str) -> bool:
    normalized = _normalize(text)
    if len(normalized.strip()) < 20:
        return True
    return any(pattern in normalized for pattern in _GARBAGE_CONTEXT_PATTERNS)


_UNANSWERABLE_TYPES = {"unanswerable", "off_topic", "out_of_scope", "no_info"}


def _ragas_samples(qa_rows: list[dict[str, Any]], chunks_by_qid: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    out = []
    for row in qa_rows:
        if row.get("skip_reason") or row.get("error") or not row.get("answer"):
            continue
        # Unanswerable/off-topic questions are evaluated via graceful_rejection_rate,
        # not RAG quality — their ground_truth is empty so RAGAS scores would be meaningless.
        if (row.get("question_type") or "") in _UNANSWERABLE_TYPES:
            continue
        # Prefer text_preview (capped at 500 chars) over full parent_text to keep RAGAS
        # judge focused. Cap at _CONTEXT_MAX_CHARS regardless to limit token usage.
        # Filter out garbage contexts (LLM meta-responses stored during bad ingestion).
        contexts = [
            c
            for c in [
                str(chunk.get("text_preview") or chunk.get("text") or "")[:_CONTEXT_MAX_CHARS]
                for chunk in chunks_by_qid.get(str(row.get("question_id")), [])
                if str(chunk.get("text_preview") or chunk.get("text") or "").strip()
            ]
            if not _is_garbage_context(c)
        ]
        if not contexts:
            contexts = [
                str(source.get("caption") or source.get("document_name") or "")
                for source in row.get("sources", [])
                if str(source.get("caption") or source.get("document_name") or "").strip()
                and not _is_garbage_context(str(source.get("caption") or ""))
            ]
        ground_truth = row.get("ground_truth") or row.get("golden_answer")
        if ground_truth and contexts:
            out.append(
                {
                    "question_id": row.get("question_id"),
                    "question": row.get("question"),
                    "answer": row.get("answer"),
                    "ground_truth": ground_truth,
                    "contexts": contexts,
                }
            )
    return out


def _fallback_ragas_scores(sample: dict[str, Any], chunks: list[dict[str, Any]]) -> dict[str, float]:
    contexts = " ".join(str(value) for value in sample.get("contexts") or [])
    answer = str(sample.get("answer") or "")
    ground_truth = str(sample.get("ground_truth") or "")
    question = str(sample.get("question") or "")
    return {
        "faithfulness": _token_f1(answer, contexts),
        # When contexts are available, compare answer against contexts (grounding proxy)
        # rather than question (lexical overlap proxy) — closer to RAGAS semantics.
        "answer_relevancy": _token_f1(answer, contexts) if contexts else _token_f1(answer, question),
        "context_precision": _context_precision(chunks, sample),
        "context_recall": _token_f1(contexts, ground_truth),
        "answer_correctness": _token_f1(answer, ground_truth),
    }


def _summarize_ragas(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for name in RAG_THRESHOLDS:
        values = [
            float(row["metrics"][name])
            for row in rows
            if isinstance((row.get("metrics") or {}).get(name), (int, float))
        ]
        summary[name] = statistics.mean(values) if values else 0.0
    summary["passed"] = all(
        summary.get(metric) is not None and summary[metric] >= threshold
        for metric, threshold in RAG_THRESHOLDS.items()
    )
    return summary


def _metric_value(raw: dict[str, Any], metric: str) -> float | None:
    aliases = {
        "answer_relevancy": ["answer_relevancy", "answer_relevance"],
        "context_precision": ["context_precision"],
        "context_recall": ["context_recall"],
        "answer_correctness": ["answer_correctness"],
        "faithfulness": ["faithfulness"],
    }
    for name in aliases.get(metric, [metric]):
        value = raw.get(name)
        if isinstance(value, (int, float)) and _is_finite_number(value):
            return float(value)
    return None


def _install_ragas_vertexai_compat() -> None:
    module_name = "langchain_community.chat_models.vertexai"
    if module_name in sys.modules:
        return
    module = types.ModuleType(module_name)

    class ChatVertexAI:
        pass

    module.ChatVertexAI = ChatVertexAI
    sys.modules[module_name] = module


def _group_by_question(retrieval_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in retrieval_rows:
        grouped.setdefault(str(row.get("question_id")), []).append(row)
    return grouped


def _document_hit(row: dict[str, Any], chunks: list[dict[str, Any]]) -> bool:
    expected = _basename(row.get("source_doc") or row.get("doc_id") or "")
    candidates = []
    for source in row.get("sources", []):
        candidates.append(str(source.get("document_name") or ""))
        candidates.append(str(source.get("document_id") or ""))
    for chunk in chunks:
        candidates.append(str(chunk.get("doc_name") or chunk.get("document_name") or ""))
        candidates.append(str(chunk.get("doc_id") or chunk.get("document_id") or ""))
    return any(_basename(candidate) == expected or expected in _normalize(candidate) for candidate in candidates)


def _expected_chunk_hit(row: dict[str, Any], chunks: list[dict[str, Any]]) -> bool | None:
    expected_values = row.get("expected_chunk_ids") or row.get("expected_chunk_id") or []
    if isinstance(expected_values, str):
        expected_values = [expected_values]
    expected = {str(v) for v in expected_values if str(v).strip()}
    if not expected:
        return None
    found: set[str] = set()
    for chunk in chunks:
        for key in ("chunk_id", "stable_parent_key", "stable_chunk_key"):
            value = str(chunk.get(key) or "").strip()
            if value:
                found.add(value)
    normalized_found = {_normalize(value) for value in found}
    return any(
        exp in found
        or _normalize(exp) in normalized_found
        or any(exp in item or _normalize(exp) in _normalize(item) for item in found)
        for exp in expected
    )


def _page_hit(row: dict[str, Any], chunks: list[dict[str, Any]]) -> bool | None:
    expected = row.get("expected_page")
    if expected is None or expected == "":
        return None
    if chunks and not any(chunk.get("page_number_source") == "pdf_page" for chunk in chunks):
        return None
    expected_text = str(expected)
    return any(str(chunk.get("page") or chunk.get("page_number") or "") == expected_text for chunk in chunks)


def _stale_sources(row: dict[str, Any]) -> list[dict[str, Any]]:
    effective = {str(doc_id) for doc_id in row.get("effective_document_ids") or [] if str(doc_id).strip()}
    if not effective:
        # No per-user ACL data recorded — cannot determine which sources are unauthorized.
        # Returning [] avoids false-positive ACL violations for admin/unrestricted test accounts.
        return []
    stale = []
    for source in row.get("sources", []):
        document_id = str((source or {}).get("document_id") or "").strip()
        if document_id and document_id not in effective:
            stale.append(source)
    return stale


def _context_precision(chunks: list[dict[str, Any]], sample: dict[str, Any]) -> float:
    if not chunks:
        return 0.0
    relevant = 0
    ground = _normalize(sample.get("ground_truth"))
    for chunk in chunks:
        text = _normalize(chunk.get("text") or chunk.get("text_preview") or "")
        if text and _token_overlap(text, ground) > 0:
            relevant += 1
    return relevant / len(chunks)


def _is_answered(row: dict[str, Any]) -> bool:
    if row.get("error") or not str(row.get("answer") or "").strip():
        return False
    if row.get("fallback") or row.get("outcome") in {3, "3", "NO_INFO"}:
        return False
    if "khong tim thay" in _normalize(row.get("answer", "")):
        return False
    return True


def _token_f1(answer: Any, reference: Any) -> float:
    a = _tokens(answer)
    r = _tokens(reference)
    if not a or not r:
        return 0.0
    overlap = len(a & r)
    if overlap == 0:
        return 0.0
    precision = overlap / len(a)
    recall = overlap / len(r)
    return 2 * precision * recall / (precision + recall)


def _token_overlap(left: str, right: str) -> int:
    return len(_tokens(left) & _tokens(right))


def _tokens(text: Any) -> set[str]:
    return {t for t in re.findall(r"\w+", _normalize(text)) if len(t) > 1}


def _normalize(text: Any) -> str:
    raw = str(text or "").lower()
    without_accents = "".join(
        ch for ch in unicodedata.normalize("NFKD", raw) if not unicodedata.combining(ch)
    )
    return re.sub(r"\s+", " ", re.sub(r"[_\W]+", " ", without_accents)).strip()


def _basename(value: Any) -> str:
    return _normalize(str(value or "").replace("\\", "/").rsplit("/", 1)[-1])


def _mean_bool(values: list[bool]) -> float | None:
    if not values:
        return None
    return sum(1 for value in values if value) / len(values)


def _safe_div(num: int, den: int) -> float | None:
    return num / den if den else None


def _is_finite_number(value: int | float) -> bool:
    return value == value and value not in {float("inf"), float("-inf")}


def _gte(value: Any, threshold: float) -> bool:
    return isinstance(value, (int, float)) and _is_finite_number(value) and float(value) >= threshold


def _lt(value: Any, threshold: float) -> bool:
    return isinstance(value, (int, float)) and _is_finite_number(value) and float(value) < threshold


def _recommended_actions(failed: list[str]) -> list[str]:
    actions = []
    if any(name in failed for name in ("faithfulness", "answer_correctness", "hallucination_rate")):
        actions.append("Tune prompt grounding, answer synthesis, and refusal policy before Phase 2.")
    if any(name in failed for name in ("context_precision", "context_recall", "answer_relevancy")):
        actions.append("Improve retrieval ranking, chunking, metadata filters, and query rewriting.")
    if any(name in failed for name in ("first_token_latency_p95_seconds", "total_latency_p95_seconds", "concurrent_users")):
        actions.append("Optimize SSE path, model latency, worker capacity, and cache strategy; rerun 50-user cold load.")
    if any(name in failed for name in ("graceful_rejection_rate", "access_control_accuracy")):
        actions.append("Fix safety and ACL behavior; add regression tests for denied-source leakage.")
    return actions or ["All checkpoint thresholds passed; continue Phase 2."]
