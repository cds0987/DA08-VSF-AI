"""Sparse encode BM25 thật — BẢN ĐỐI XỨNG của mcp-service _sparse_encode_query.

BM25 = IDF * TF-bão-hoà(length-norm). Chia 2 trách nhiệm:
  - Qdrant tính IDF phía server (SparseVectorParams modifier=IDF) -> KHÔNG encode IDF ở client.
  - Phía DOCUMENT (ingest, hàm `sparse_encode_document`): value = TF bão hoà có chuẩn hoá
    độ dài tài liệu  tf*(k1+1) / (tf + k1*(1 - b + b*dl/avgdl)).
  - Phía QUERY (search, hàm `sparse_encode_query`): value = TF thô của câu hỏi (Qdrant nhân IDF).

INDEX (token->bucket) PHẢI Y HỆT giữa document & query VÀ giữa rag-worker & mcp, nếu không
indices không trùng -> sparse vô dụng. mcp-service/app/core/vectorstore.py giữ bản query đối
xứng; golden parity test (tests/core_engine/test_sparse_parity.py) chốt index trùng.

Encode index: token \\w+ lowercase -> crc32 % 2^16 (65536 bucket), gộp count theo bucket.

avgdl (độ dài tài liệu trung bình toàn corpus) là HẰNG CẤU HÌNH (env BM25_AVGDL) -> 1 nguồn
sự thật cho cả ingest thường LẪN migrate => mọi point dùng cùng length-norm (nhất quán). Script
migrate đo avgdl thực của corpus để KHUYẾN NGHỊ chỉnh env, nhưng encode luôn theo hằng này.
Sai lệch avgdl chỉ làm length-norm hơi lệch (KHÔNG phá parity: query không dùng avgdl, index
không phụ thuộc avgdl) -> non-fatal.

Nếu sửa file này (token->index, k1/b mặc định), PHẢI bump SPARSE_ENCODING_VERSION ở
core_engine/contract.py (và mcp) + sửa đối xứng mcp _sparse_encode_query.
"""
from __future__ import annotations

import binascii
import os
import re
from collections import Counter

_SPARSE_BUCKETS = 1 << 16  # 65536 — PHẢI khớp mcp

# Tham số BM25. k1=1.2, b=0.75 là chuẩn sách giáo khoa. avgdl override qua env (đo từ corpus
# lúc migrate; default ~180 token/chunk hợp với child_max_words + section title + ctx header).
BM25_K1 = float(os.getenv("BM25_K1", "1.2") or "1.2")
BM25_B = float(os.getenv("BM25_B", "0.75") or "0.75")
BM25_AVGDL = float(os.getenv("BM25_AVGDL", "180") or "180")


def _bucket_counts(text: str) -> tuple[dict[int, int], int]:
    """token \\w+ lowercase -> {bucket: count}, và tổng token (dl = document length)."""
    tokens = re.findall(r"\w+", text.lower())
    if not tokens:
        return {}, 0
    buckets: dict[int, int] = {}
    for token, count in Counter(tokens).items():
        idx = binascii.crc32(token.encode()) % _SPARSE_BUCKETS
        buckets[idx] = buckets.get(idx, 0) + count
    return buckets, len(tokens)


def sparse_encode_document(
    text: str,
    *,
    avgdl: float | None = None,
    k1: float = BM25_K1,
    b: float = BM25_B,
) -> tuple[list[int], list[float]]:
    """Phía DOCUMENT (ingest): value = TF bão hoà BM25 có length-norm. IDF do Qdrant nhân."""
    buckets, dl = _bucket_counts(text)
    if not buckets:
        return [], []
    avg = float(avgdl) if avgdl and float(avgdl) > 0 else BM25_AVGDL
    if avg <= 0:
        avg = 1.0
    denom_norm = 1.0 - b + b * (dl / avg)
    indices = sorted(buckets)
    values = []
    for i in indices:
        tf = float(buckets[i])
        values.append(tf * (k1 + 1.0) / (tf + k1 * denom_norm))
    return indices, values


def sparse_encode_query(text: str) -> tuple[list[int], list[float]]:
    """Phía QUERY (search): value = TF thô của câu hỏi. Qdrant nhân IDF (modifier=IDF)."""
    buckets, _dl = _bucket_counts(text)
    if not buckets:
        return [], []
    indices = sorted(buckets)
    return indices, [float(buckets[i]) for i in indices]


# Alias tương thích ngược: code/test cũ gọi sparse_encode() = bản DOCUMENT.
def sparse_encode(text: str) -> tuple[list[int], list[float]]:
    return sparse_encode_document(text)
