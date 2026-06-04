"""Text primitives tất định dùng chung (offline embed + lexical rerank).

Không phụ thuộc AI/model — chỉ tokenize, overlap, hash-embed. Tách riêng để
offline provider và lexical reranker chia sẻ, tránh lặp.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import List

_WORD = re.compile(r"\w+", re.UNICODE)


def tokens(text: str) -> List[str]:
    return _WORD.findall((text or "").lower())


def overlap_score(query: str, text: str) -> float:
    """Tỷ lệ token của query được phủ bởi `text`, trong [0,1]."""
    q = set(tokens(query))
    if not q:
        return 0.0
    d = set(tokens(text))
    return round(len(q & d) / len(q), 4)


def hash_embed(texts: List[str], dim: int) -> List[List[float]]:
    """Embedder offline tất định (KHÔNG semantic thật) — dev/eval/selftest.

    Hash token vào `dim` chiều rồi L2-normalize: text chia sẻ nhiều token →
    vector gần nhau (cosine). Bất biến: ingest & query qua cùng hàm/dimension
    (embedding.md §2). Production thay bằng provider thật cùng chữ ký.
    """
    out: List[List[float]] = []
    for text in texts:
        vec = [0.0] * dim
        for tok in tokens(text):
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            idx = h % dim
            vec[idx] += 1.0 if (h // dim) % 2 == 0 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        out.append([v / norm for v in vec])
    return out
