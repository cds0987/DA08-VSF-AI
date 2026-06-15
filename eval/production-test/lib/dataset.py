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


def load_questions(dataset_root: Path, dataset: str, *, limit: int | None, offset: int) -> tuple[Any, list[GoldenQA]]:
    bundle = load_dataset(dataset_root / dataset)
    candidates = list(bundle.questions[max(0, offset):])
    questions = candidates[:limit] if limit else candidates
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
