"""Sparse encode (BM25-lite) — BẢN ĐỐI XỨNG của mcp-service _sparse_encode.

PHẢI cho ra giá trị Y HỆT mcp-service/app/core/vectorstore.py::_sparse_encode:
ingest (rag-worker) sinh sparse vector phải dùng CÙNG cách map token->index với
search (mcp), nếu không indices không trùng -> sparse vô dụng. Drift bắt bởi golden
parity test (tests/core_engine/test_sparse_parity.py) — cùng input -> cùng output.

Nếu sửa file này, PHẢI sửa đối xứng mcp-service/app/core/vectorstore.py.
Encode: token \\w+ lowercase -> crc32 % 2^16 (65536 bucket) -> count, chuẩn hoá theo tổng.
"""
from __future__ import annotations

import binascii
import re
from collections import Counter

_SPARSE_BUCKETS = 1 << 16  # 65536 — PHẢI khớp mcp


def sparse_encode(text: str) -> tuple[list[int], list[float]]:
    tokens = re.findall(r"\w+", text.lower())
    if not tokens:
        return [], []
    counts = Counter(tokens)
    result: dict[int, float] = {}
    for token, count in counts.items():
        idx = binascii.crc32(token.encode()) % _SPARSE_BUCKETS
        result[idx] = result.get(idx, 0) + count
    total = sum(result.values())
    indices = sorted(result)
    values = [result[i] / total for i in indices]
    return indices, values
