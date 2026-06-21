"""GATE (consumer runtime): parser kết quả MCP của query-service PHẢI trích ĐỦ dữ liệu từ
payload SHAPE CANONICAL (đúng cái mcp-service _hit_to_dict phát). Khoá consumer ⇔ producer:
dev refactor parser bỏ field, hoặc đổi shape canonical -> test đỏ.

Bổ trợ mcp_result_lint.py (tĩnh) bằng kiểm CHẠY THẬT: citation/nguồn KHÔNG degrade âm thầm.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.external.mcp_client import _search_result_from_payload

_CONTRACT = Path(__file__).resolve().parents[3] / "infra" / "mcp" / "tool-result-contract.yaml"


def _canonical_fields() -> list[str]:
    import yaml
    if not _CONTRACT.exists():
        pytest.skip("tool-result-contract.yaml không có trong checkout này")
    c = yaml.safe_load(_CONTRACT.read_text(encoding="utf-8"))
    return list(c["rag_search_result"]["canonical_fields"])


def _sample(field: str):
    if field == "score":
        return 0.87
    if field == "page_number":
        return 3
    if field == "heading_path":
        return ["A", "B"]
    return f"val_{field}"


def test_parser_extracts_all_canonical_fields():
    """Payload canonical (đủ field mcp phát) -> SearchResult điền ĐỦ field trọng yếu, không rỗng."""
    fields = _canonical_fields()
    item = {f: _sample(f) for f in fields}
    sr = _search_result_from_payload(item)

    # field trọng yếu cho citation/nguồn PHẢI không rỗng (degrade = mất link tài liệu).
    assert sr.chunk_id == "val_chunk_id", "mất id -> không map được nguồn"
    assert sr.document_id == "val_document_id"
    assert sr.document_name == "val_document_name", "mất tên tài liệu -> chip nguồn trống"
    assert sr.parent_text == "val_parent_text", "mất nội dung -> LLM thiếu ngữ cảnh"
    assert sr.score == 0.87
    assert sr.source_gcs_uri == "val_source_gcs_uri", "mất source uri -> mở tài liệu hỏng"
    assert list(sr.heading_path) == ["A", "B"]
    assert sr.page_number == 3


def test_parser_survives_empty_item():
    """Item rỗng -> KHÔNG raise (fail-safe), chỉ rỗng field — parser không được crash graph."""
    sr = _search_result_from_payload({})
    assert sr.chunk_id == "" and sr.document_name == ""
