from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.dataset import GoldenQA, _select_by_doc  # noqa: E402


def _qa(question_id: str, doc_id: str) -> GoldenQA:
    return GoldenQA(
        question_id=question_id,
        question=f"Question {question_id}",
        golden_answer=f"Answer {question_id}",
        doc_id=doc_id,
    )


def test_select_by_doc_honors_include_order_and_per_doc_limit() -> None:
    questions = [
        _qa("labor-1", "Bộ luật lao động 2019.pdf"),
        _qa("pci-1", "PCI_Employee_Handbook.pdf"),
        _qa("pci-2", "PCI_Employee_Handbook.pdf"),
        _qa("mau-1", "Mau-noi-quy-lao-dong-2024.docx"),
        _qa("mau-2", "Mau-noi-quy-lao-dong-2024.docx"),
    ]

    selected = _select_by_doc(
        questions,
        include_doc_ids=("Mau-noi-quy-lao-dong-2024.docx", "PCI_Employee_Handbook.pdf"),
        exclude_doc_ids=("Bộ luật lao động 2019.pdf",),
        questions_per_doc=1,
    )

    assert [qa.question_id for qa in selected] == ["mau-1", "pci-1"]
    assert all(qa.doc_id != "Bộ luật lao động 2019.pdf" for qa in selected)


def test_select_by_doc_limits_each_doc_when_no_include_list() -> None:
    questions = [
        _qa("a-1", "a.pdf"),
        _qa("a-2", "a.pdf"),
        _qa("b-1", "b.pdf"),
        _qa("b-2", "b.pdf"),
    ]

    selected = _select_by_doc(
        questions,
        include_doc_ids=(),
        exclude_doc_ids=(),
        questions_per_doc=1,
    )

    assert [qa.question_id for qa in selected] == ["a-1", "b-1"]
