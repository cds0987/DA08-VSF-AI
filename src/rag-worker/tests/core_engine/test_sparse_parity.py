"""Golden parity test: rag-worker sparse_encode PHẢI khớp mcp _sparse_encode.

Golden lấy TRỰC TIẾP từ mcp-service/app/core/vectorstore.py::_sparse_encode (nguồn chuẩn).
Lệch = sparse ingest (rag-worker) không trùng index với search (mcp) -> hybrid vô dụng.
"""
from __future__ import annotations

from core_engine.vectorstore.sparse import sparse_encode

# (input, expected_indices, expected_values) — chốt từ mcp encoder.
_GOLDEN = [
    ("hello world hello", [4419, 42630], [1 / 3, 2 / 3]),
    ("nghi phep nam", [3014, 30779, 47834], [1 / 3, 1 / 3, 1 / 3]),
    ("", [], []),
]


def test_sparse_encode_matches_mcp_golden():
    for text, exp_idx, exp_val in _GOLDEN:
        idx, val = sparse_encode(text)
        assert idx == exp_idx, f"{text!r}: indices {idx} != {exp_idx}"
        assert len(val) == len(exp_val)
        for got, want in zip(val, exp_val):
            assert abs(got - want) < 1e-9, f"{text!r}: value {got} != {want}"


def test_sparse_encode_deterministic_and_normalized():
    idx, val = sparse_encode("a a b c c c")
    assert idx == sorted(idx)                  # indices sorted
    assert abs(sum(val) - 1.0) < 1e-9          # chuẩn hoá theo tổng count
