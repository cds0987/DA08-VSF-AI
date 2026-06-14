from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".xlsx", ".csv", ".pptx", ".md"}
GOLDEN_DIR_NAMES = {"goldenq", "goldenqa"}


@dataclass(frozen=True)
class GoldenQA:
    question_id: str
    question: str
    golden_answer: str
    doc_id: str
    expected_chunk_ids: list[str] = field(default_factory=list)
    expected_page: str | int | None = None
    expected_section: str | None = None
    topic: str | None = None
    question_type: str | None = None
    difficulty: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceDocument:
    path: Path
    relative_path: str
    extension: str
    upload_supported: bool


@dataclass(frozen=True)
class DatasetBundle:
    name: str
    root: Path
    golden_path: Path
    questions: list[GoldenQA]
    documents: list[SourceDocument]
    missing_doc_ids: list[str]
    malformed_rows: list[dict[str, Any]]


def discover_datasets(dataset_root: Path, only: str | None = None) -> list[Path]:
    roots = [p for p in sorted(dataset_root.iterdir()) if p.is_dir()]
    if only:
        roots = [p for p in roots if p.name == only]
    return roots


def load_dataset(root: Path) -> DatasetBundle:
    golden_path = _find_golden(root)
    questions, malformed_rows = _load_golden(golden_path)
    documents = _find_documents(root)
    doc_keys = _document_keys(documents)
    missing = sorted({qa.doc_id for qa in questions if qa.doc_id and _normalize_key(qa.doc_id) not in doc_keys})
    return DatasetBundle(
        name=root.name,
        root=root,
        golden_path=golden_path,
        questions=questions,
        documents=documents,
        missing_doc_ids=missing,
        malformed_rows=malformed_rows,
    )


def _find_golden(root: Path) -> Path:
    candidates = [
        root / "goldenqa" / "golden_qa.jsonl",
        root / "goldenq" / "golden_qa.jsonl",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"No golden_qa.jsonl found under {root}")


def _load_golden(path: Path) -> tuple[list[GoldenQA], list[dict[str, Any]]]:
    rows: list[GoldenQA] = []
    malformed: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as fh:
        for line_no, line in enumerate(fh, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                item = json.loads(text)
                question_id = str(item["question_id"])
                question = str(item["question"])
                answer = str(item["golden_answer"])
                doc_id = str(item["doc_id"])
            except Exception as exc:  # noqa: BLE001
                malformed.append({"line": line_no, "error": str(exc), "raw": text[:500]})
                continue
            expected = item.get("expected_chunk_ids") or []
            if not isinstance(expected, list):
                expected = []
            rows.append(
                GoldenQA(
                    question_id=question_id,
                    question=question,
                    golden_answer=answer,
                    doc_id=doc_id,
                    expected_chunk_ids=[str(v) for v in expected],
                    expected_page=item.get("expected_page") or item.get("page") or item.get("expected_page_number"),
                    expected_section=(
                        str(item.get("expected_section") or item.get("section") or item.get("heading"))
                        if item.get("expected_section") or item.get("section") or item.get("heading")
                        else None
                    ),
                    topic=str(item.get("topic")) if item.get("topic") is not None else None,
                    question_type=str(item.get("question_type")) if item.get("question_type") is not None else None,
                    difficulty=str(item.get("difficulty")) if item.get("difficulty") is not None else None,
                    raw=item,
                )
            )
    return rows, malformed


def _find_documents(root: Path) -> list[SourceDocument]:
    docs: list[SourceDocument] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root)
        if len(rel.parts) == 1 and rel.name.lower() == "readme.md":
            continue
        parts = {part.lower() for part in rel.parts}
        if parts & GOLDEN_DIR_NAMES:
            continue
        if path.name.lower().startswith("golden_qa"):
            continue
        ext = path.suffix.lower()
        if ext in {".json", ".jsonl"}:
            continue
        docs.append(
            SourceDocument(
                path=path,
                relative_path=rel.as_posix(),
                extension=ext.lstrip("."),
                upload_supported=ext in SUPPORTED_EXTENSIONS,
            )
        )
    return docs


def _document_keys(documents: list[SourceDocument]) -> set[str]:
    keys: set[str] = set()
    for doc in documents:
        keys.add(_normalize_key(doc.relative_path))
        keys.add(_normalize_key(Path(doc.relative_path).name))
    return keys


def _normalize_key(value: str) -> str:
    return value.replace("\\", "/").strip().lower()
