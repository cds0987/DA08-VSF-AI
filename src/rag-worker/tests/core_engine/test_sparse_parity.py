"""Golden parity test BM25: index (token->bucket) PHẢI khớp giữa document/query VÀ
giữa rag-worker và mcp-service.

BM25 thật tách value 2 phía (document = TF bão hoà; query = TF thô) nên KHÔNG còn so
value document==query. Cái BẮT BUỘC trùng là INDEX: nếu document & query (hoặc rag-worker
& mcp) ánh xạ token -> bucket khác nhau, indices không gặp nhau trong Qdrant -> sparse vô
dụng (im lặng). Golden query value chốt từ mcp _sparse_encode_query (nguồn chuẩn phía đọc).

Nếu sửa token->bucket, PHẢI sửa mcp _sparse_encode_query + bump SPARSE_ENCODING_VERSION.
"""
from __future__ import annotations

from core_engine.vectorstore.sparse import (
    BM25_B,
    BM25_K1,
    sparse_encode_document,
    sparse_encode_query,
)

# (input, expected_indices, expected_query_values) — index ổn định theo crc32%2^16;
# query value = TF thô. PHẢI khớp mcp-service _sparse_encode_query.
_GOLDEN = [
    ("hello world hello", [4419, 42630], [1.0, 2.0]),
    ("nghi phep nam", [3014, 30779, 47834], [1.0, 1.0, 1.0]),
    ("", [], []),
]


def test_query_encode_matches_mcp_golden():
    for text, exp_idx, exp_val in _GOLDEN:
        idx, val = sparse_encode_query(text)
        assert idx == exp_idx, f"{text!r}: query indices {idx} != {exp_idx}"
        assert val == exp_val, f"{text!r}: query values {val} != {exp_val}"


def test_document_and_query_share_indices():
    """Index document == index query (cùng tokenizer/bucket) -> gặp nhau trong Qdrant."""
    for text, exp_idx, _ in _GOLDEN:
        d_idx, _ = sparse_encode_document(text)
        q_idx, _ = sparse_encode_query(text)
        assert d_idx == q_idx == exp_idx, f"{text!r}: doc {d_idx} vs query {q_idx}"


def test_document_value_is_bm25_saturated():
    """value document = tf*(k1+1)/(tf + k1*(1-b+b*dl/avgdl)) — tính tay, avgdl mặc định."""
    text = "hello world hello"  # dl=3; bucket 42630=hello(tf=2), 4419=world(tf=1)
    avgdl = 180.0
    idx, val = sparse_encode_document(text, avgdl=avgdl)
    denom = 1.0 - BM25_B + BM25_B * (3 / avgdl)
    want = {
        42630: 2.0 * (BM25_K1 + 1) / (2.0 + BM25_K1 * denom),
        4419: 1.0 * (BM25_K1 + 1) / (1.0 + BM25_K1 * denom),
    }
    got = dict(zip(idx, val))
    for bucket, w in want.items():
        assert abs(got[bucket] - w) < 1e-9, f"bucket {bucket}: {got[bucket]} != {w}"


def test_longer_doc_gets_lower_tf_weight():
    """Length-norm: cùng tf, tài liệu DÀI hơn -> weight THẤP hơn (đặc trưng BM25 b>0)."""
    short = "alpha alpha"            # dl=2
    long = "alpha alpha " + " ".join(f"w{i}" for i in range(50))  # dl=52, alpha tf=2
    bucket = sparse_encode_document(short)[0][0]
    v_short = dict(zip(*sparse_encode_document(short)))[bucket]
    v_long = dict(zip(*sparse_encode_document(long)))[bucket]
    assert v_long < v_short
