from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


PRODUCTION_TEST_ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = PRODUCTION_TEST_ROOT.parent

_DATASET_LOADER = EVAL_ROOT / "lib" / "dataset_loader.py"
_SPEC = importlib.util.spec_from_file_location("production_test_dataset_loader", _DATASET_LOADER)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Cannot load dataset loader from {_DATASET_LOADER}")
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

GoldenQA = _MODULE.GoldenQA
load_dataset = _MODULE.load_dataset

_UNANSWERABLE_TYPES = {"unanswerable", "off_topic", "out_of_scope", "no_info"}


def load_questions(
    dataset_root: Path,
    dataset: str,
    *,
    limit: int | None,
    offset: int,
    include_doc_ids: tuple[str, ...] = (),
    exclude_doc_ids: tuple[str, ...] = (),
    questions_per_doc: int | None = None,
) -> tuple[Any, list[GoldenQA]]:
    bundle = load_dataset(dataset_root / dataset)
    candidates = _select_by_doc(
        bundle.questions,
        include_doc_ids=include_doc_ids,
        exclude_doc_ids=exclude_doc_ids,
        questions_per_doc=questions_per_doc,
    )

    # Always inject labeled unanswerable/off-topic questions so graceful_rejection_rate
    # is measurable in every eval run (not just when limit > dataset size).
    # Exception: very small runs (smoke test with limit=1) skip injection to stay fast.
    unanswerable = [q for q in candidates if (q.question_type or "") in _UNANSWERABLE_TYPES]
    regular = [q for q in candidates if (q.question_type or "") not in _UNANSWERABLE_TYPES]
    regular = list(regular[max(0, offset):])

    if not unanswerable or (limit and limit < len(unanswerable) + 2):
        # Smoke/tiny run — select normally without injection
        questions = regular[:limit] if limit else regular
    else:
        # Reserve slots for unanswerable questions, fill the rest with regular
        regular_slots = (limit - len(unanswerable)) if limit else None
        if regular_slots is not None:
            regular = regular[:max(0, regular_slots)]
        questions = regular + unanswerable

    return bundle, questions


def golden_row(qa: GoldenQA) -> dict[str, Any]:
    return {
        "question_id": qa.question_id,
        "question": qa.question,
        "golden_answer": qa.golden_answer,
        "ground_truth": qa.golden_answer,
        "doc_id": qa.doc_id,
        "source_doc": qa.doc_id,
        "expected_chunk_ids": qa.expected_chunk_ids,
        "expected_chunk_id": qa.expected_chunk_ids[0] if qa.expected_chunk_ids else None,
        "expected_page": qa.expected_page,
        "expected_section": qa.expected_section,
        "topic": qa.topic,
        "question_type": qa.question_type,
        "difficulty": qa.difficulty,
    }


def _select_by_doc(
    questions: list[GoldenQA],
    *,
    include_doc_ids: tuple[str, ...],
    exclude_doc_ids: tuple[str, ...],
    questions_per_doc: int | None,
) -> list[GoldenQA]:
    excluded = {_norm_doc_id(value) for value in exclude_doc_ids}
    if include_doc_ids:
        selected: list[GoldenQA] = []
        seen_ids: set[str] = set()
        for include in include_doc_ids:
            include_key = _norm_doc_id(include)
            matches = [
                qa for qa in questions
                if _doc_matches(qa.doc_id, include_key) and _norm_doc_id(qa.doc_id) not in excluded
            ]
            if questions_per_doc:
                matches = matches[:questions_per_doc]
            for qa in matches:
                if qa.question_id not in seen_ids:
                    selected.append(qa)
                    seen_ids.add(qa.question_id)
        return selected

    selected = [
        qa for qa in questions
        if _norm_doc_id(qa.doc_id) not in excluded
    ]
    if not questions_per_doc:
        return selected

    counts: dict[str, int] = {}
    limited: list[GoldenQA] = []
    for qa in selected:
        key = _norm_doc_id(qa.doc_id)
        count = counts.get(key, 0)
        if count >= questions_per_doc:
            continue
        limited.append(qa)
        counts[key] = count + 1
    return limited


def _doc_matches(doc_id: str, expected_normalized: str) -> bool:
    doc_key = _norm_doc_id(doc_id)
    doc_name = _norm_doc_id(Path(doc_id).name)
    return doc_key == expected_normalized or doc_name == expected_normalized


def _norm_doc_id(value: str) -> str:
    return value.replace("\\", "/").strip().lower()
