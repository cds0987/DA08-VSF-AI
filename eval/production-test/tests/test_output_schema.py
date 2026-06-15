from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.production_client import retrieval_rows_from_probe


def test_retrieval_rows_include_phase_1_5_fields() -> None:
    rows = retrieval_rows_from_probe(
        question_id="q1",
        source_doc="Doc.pdf",
        probe={
            "ok": True,
            "results": [
                {
                    "chunk_id": "c1",
                    "document_id": "d1",
                    "document_name": "Doc.pdf",
                    "score": 0.9,
                    "page_number": 2,
                    "heading_path": ["A"],
                    "caption": "cap",
                    "parent_text": "full text",
                }
            ],
        },
        fallback_sources=[],
    )

    row = rows[0]
    for key in (
        "question_id",
        "rank",
        "chunk_id",
        "document_id",
        "document_name",
        "source_doc",
        "score",
        "page_number",
        "heading_path",
        "caption",
        "text",
        "text_preview",
        "probe_ok",
        "probe_error",
    ):
        assert key in row
    assert row["text"] == "full text"
