from lib.metrics import compute_retrieval_diagnostics
from run_eval import _normalize_retrieval_chunk


def test_expected_chunk_hit_matches_stable_parent_key() -> None:
    qa_rows = [
        {
            "question_id": "q1",
            "source_doc": "Mau-noi-quy-lao-dong-2024.docx",
            "expected_chunk_ids": ["mau_noi_quy_lao_dong_2024_chunk_0005"],
            "effective_document_ids": ["doc-1"],
            "sources": [{"document_id": "doc-1", "document_name": "Mau-noi-quy-lao-dong-2024.docx"}],
        }
    ]
    retrieval_rows = [
        {
            "question_id": "q1",
            "chunk_id": "doc-1::p4::c0",
            "stable_parent_key": "mau_noi_quy_lao_dong_2024_chunk_0005",
            "stable_chunk_key": "mau_noi_quy_lao_dong_2024_chunk_0005",
            "document_id": "doc-1",
            "document_name": "Mau-noi-quy-lao-dong-2024.docx",
            "score": 0.91,
        }
    ]

    diagnostics = compute_retrieval_diagnostics(qa_rows, retrieval_rows)

    assert diagnostics["expected_chunk_hit_at_k"] == 1.0
    assert diagnostics["stale_source_count"] == 0


def test_retrieval_diagnostics_counts_sources_outside_effective_scope() -> None:
    diagnostics = compute_retrieval_diagnostics(
        [
            {
                "question_id": "q1",
                "source_doc": "doc.pdf",
                "effective_document_ids": ["doc-1"],
                "sources": [{"document_id": "old-doc", "document_name": "doc.pdf"}],
            }
        ],
        [],
    )

    assert diagnostics["stale_source_count"] == 1
    assert diagnostics["stale_source_rows"][0]["stale_sources"][0]["document_id"] == "old-doc"


def test_normalize_retrieval_chunk_derives_stable_key_from_runtime_uuid_chunk_id() -> None:
    row = _normalize_retrieval_chunk(
        {
            "chunk_id": "uploaded-doc-uuid::p4::c0",
            "document_id": "uploaded-doc-uuid",
            "document_name": "Mau-noi-quy-lao-dong-2024.docx",
            "parent_text": "noi dung",
            "score": 0.8,
        },
        question_id="q1",
        source_doc="Mau-noi-quy-lao-dong-2024.docx",
        uploaded_document_id="uploaded-doc-uuid",
        rank=1,
    )

    assert row["stable_parent_key"] == "mau_noi_quy_lao_dong_2024_chunk_0005"
    assert row["stable_chunk_key"] == "mau_noi_quy_lao_dong_2024_chunk_0005"
