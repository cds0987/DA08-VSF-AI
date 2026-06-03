"""HaystackSettings — cấu hình KHÔNG-AI của pipeline (split · retrieval · store).

Cấu hình AI (model/endpoint/key cho embed/caption/rerank) thuộc về AI gateway
(`haystack_interface.ai`), KHÔNG ở đây — giữ ranh giới: settings này lo Haystack
pipeline + vector store; provider lo outbound AI.

`embed_dimension` validate khớp index — đổi dimension là MIGRATION, không config
edit (embedding.md §4 / ingestion.md §8). Index id encode dimension.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# BGE-M3 / nhiều embed model phổ biến: 1024 dims. Index id encode dimension này.
DEFAULT_EMBED_DIM = 1024


@dataclass(frozen=True)
class HaystackSettings:
    # Dimension (phải khớp provider AI đang dùng — factory đảm bảo).
    embed_dimension: int = DEFAULT_EMBED_DIM

    # Section split (ingestion.md §5) + parent/child (entities.Chunk).
    parent_max_words: int = 220      # ~512-1024 tokens
    child_max_words: int = 90        # ~128-256 tokens
    child_overlap_words: int = 15

    # Retrieval (search.md §3,4).
    top_k_candidates: int = 20       # trước rerank
    rerank_top_k: int = 3            # sau rerank (Top-3)
    rerank_threshold: float = 0.7    # BGE-Reranker / LLM threshold

    # Vector store.
    collection: str = "rag_chatbot"

    def index_id(self) -> str:
        """Index id encode dimension => đổi dimension là migration."""
        return f"{self.collection}__d{self.embed_dimension}"


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw and raw.strip() else default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw and raw.strip() else default


def load_settings() -> HaystackSettings:
    """Build settings từ env, fallback default chạy-được-ngay."""
    return HaystackSettings(
        embed_dimension=_int("EMBED_DIMENSION", DEFAULT_EMBED_DIM),
        parent_max_words=_int("SECTION_MAX_WORDS", 220),
        child_max_words=_int("CHILD_MAX_WORDS", 90),
        child_overlap_words=_int("CHILD_OVERLAP_WORDS", 15),
        top_k_candidates=_int("SEARCH_TOP_K", 20),
        rerank_top_k=_int("RERANK_TOP_K", 3),
        rerank_threshold=_float("RERANK_THRESHOLD", 0.7),
        collection=os.getenv("QDRANT_COLLECTION", "rag_chatbot"),
    )
