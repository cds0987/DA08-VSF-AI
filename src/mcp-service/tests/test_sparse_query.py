"""Đối xứng BM25 query: mcp _sparse_encode_query PHẢI cho ra Y HỆT golden mà rag-worker
khóa ở tests/core_engine/test_sparse_parity.py (cùng index, query value = TF thô).

Lệch giữa 2 file = ingest (rag-worker) và search (mcp) ánh xạ token->bucket khác nhau ->
hybrid vô dụng IM LẶNG. Nếu sửa, sửa cả 2 + bump SPARSE_ENCODING_VERSION.
"""
from __future__ import annotations

from app.core.vectorstore import _sparse_encode_query

# PHẢI khớp _GOLDEN trong rag-worker test_sparse_parity.py.
_GOLDEN = [
    ("hello world hello", [4419, 42630], [1.0, 2.0]),
    ("nghi phep nam", [3014, 30779, 47834], [1.0, 1.0, 1.0]),
    ("", [], []),
]


def test_sparse_encode_query_golden():
    for text, exp_idx, exp_val in _GOLDEN:
        idx, val = _sparse_encode_query(text)
        assert idx == exp_idx, f"{text!r}: indices {idx} != {exp_idx}"
        assert val == exp_val, f"{text!r}: values {val} != {exp_val}"
