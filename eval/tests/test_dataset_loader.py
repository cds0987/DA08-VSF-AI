from __future__ import annotations

import json
from pathlib import Path

from lib.dataset_loader import load_dataset


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def test_loads_goldenqa_folder(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset_new"
    dataset.mkdir(parents=True)
    (dataset / "doc.pdf").write_bytes(b"%PDF")
    _write_jsonl(
        dataset / "goldenqa" / "golden_qa.jsonl",
        [
            {
                "question_id": "q1",
                "question": "Question?",
                "golden_answer": "Answer.",
                "doc_id": "doc.pdf",
                "expected_chunk_ids": ["c1"],
            }
        ],
    )

    bundle = load_dataset(dataset)

    assert bundle.golden_path.name == "golden_qa.jsonl"
    assert len(bundle.questions) == 1
    assert len(bundle.documents) == 1
    assert bundle.missing_doc_ids == []


def test_loads_goldenq_folder_and_reports_missing_doc(tmp_path: Path) -> None:
    dataset = tmp_path / "small_test_dataset"
    (dataset / "md_output").mkdir(parents=True)
    (dataset / "md_output" / "policy.md").write_text("hello", encoding="utf-8")
    _write_jsonl(
        dataset / "goldenq" / "golden_qa.jsonl",
        [
            {
                "question_id": "q1",
                "question": "Question?",
                "golden_answer": "Answer.",
                "doc_id": "csv_output/missing.csv",
            }
        ],
    )

    bundle = load_dataset(dataset)

    assert len(bundle.questions) == 1
    assert bundle.missing_doc_ids == ["csv_output/missing.csv"]


def test_malformed_rows_are_recorded(tmp_path: Path) -> None:
    dataset = tmp_path / "broken"
    path = dataset / "goldenqa" / "golden_qa.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"question_id": "q1"}\n', encoding="utf-8")

    bundle = load_dataset(dataset)

    assert bundle.questions == []
    assert len(bundle.malformed_rows) == 1

