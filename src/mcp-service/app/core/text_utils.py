"""Text primitives tất định — BẢN RIÊNG mcp, COPY Y HỆT rag-worker text_utils.

CỰC KỲ QUAN TRỌNG: `hash_embed` phải byte-identical với rag-worker để search
offline đọc đúng vector đã ingest. Model thật (openai) thì cùng API nên không lo;
nhưng offline là hash cục bộ -> sai 1 ký tự thuật toán là search ra rác (guard
fingerprint KHÔNG bắt được vì cùng tên 'offline'/dim 256). Sửa = sửa cả 2 bên.
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
    q = set(tokens(query))
    if not q:
        return 0.0
    d = set(tokens(text))
    return round(len(q & d) / len(q), 4)


def hash_embed(texts: List[str], dim: int) -> List[List[float]]:
    out: List[List[float]] = []
    for text in texts:
        vec = [0.0] * dim
        for tok in tokens(text):
            # nosec B324 - deterministic hash for offline embeddings, not a security primitive
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            idx = h % dim
            vec[idx] += 1.0 if (h // dim) % 2 == 0 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        out.append([v / norm for v in vec])
    return out
