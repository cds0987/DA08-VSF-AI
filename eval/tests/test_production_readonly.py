from __future__ import annotations

import pytest
import asyncio
from pathlib import Path

from lib.dataset_loader import DatasetBundle, GoldenQA, SourceDocument
from run_eval import _ensure_production_document_map_ready, _production_document_map


class FakeDocumentClient:
    def __init__(self, documents: list[dict]) -> None:
        self.documents = documents
        self.upload_called = False
        self.delete_called = False

    async def list_documents(self, token: str, *, status: str | None = None, page_size: int = 100) -> list[dict]:
        if status is None:
            return self.documents
        return [doc for doc in self.documents if doc.get("status") == status]

    async def upload_document(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.upload_called = True
        raise AssertionError("production read-only mapping must not upload")

    async def delete_document(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.delete_called = True
        raise AssertionError("production read-only mapping must not delete")


def _bundle() -> DatasetBundle:
    root = Path("eval/dataset/dataset_new")
    return DatasetBundle(
        name="dataset_new",
        root=root,
        golden_path=root / "goldenqa" / "golden_qa.jsonl",
        questions=[
            GoldenQA(
                question_id="q1",
                question="Question?",
                golden_answer="Answer.",
                doc_id="Bộ luật lao động 2019.pdf",
            )
        ],
        documents=[
            SourceDocument(
                path=root / "Bộ luật lao động 2019.pdf",
                relative_path="Bộ luật lao động 2019.pdf",
                extension="pdf",
                upload_supported=True,
            )
        ],
        missing_doc_ids=[],
        malformed_rows=[],
    )


def test_production_document_map_matches_dataset_filename() -> None:
    client = FakeDocumentClient(
        [
            {
                "id": "doc-1",
                "name": "Bộ luật lao động 2019.pdf",
                "status": "indexed",
                "classification": "public",
            }
        ]
    )

    document_map = asyncio.run(
        _production_document_map(
            client,
            _bundle(),
            _bundle().questions,
            "token",
            require_indexed_docs=True,
        )
    )

    assert document_map["ok"] is True
    assert document_map["upload_map"]["Bộ luật lao động 2019.pdf"]["document_id"] == "doc-1"


def test_production_readonly_mapping_does_not_upload_or_delete() -> None:
    client = FakeDocumentClient(
        [
            {
                "document_id": "doc-1",
                "document_name": "Bộ luật lao động 2019.pdf",
                "status": "indexed",
            }
        ]
    )

    asyncio.run(_production_document_map(client, _bundle(), _bundle().questions, "token", require_indexed_docs=True))

    assert client.upload_called is False
    assert client.delete_called is False


def test_production_document_map_fails_when_indexed_doc_missing() -> None:
    document_map = asyncio.run(
        _production_document_map(
            FakeDocumentClient([]),
            _bundle(),
            _bundle().questions,
            "token",
            require_indexed_docs=True,
        )
    )

    assert document_map["ok"] is False
    with pytest.raises(RuntimeError, match="not indexed on production"):
        _ensure_production_document_map_ready(document_map)
