"""Haystack settings for split and retrieval stages."""

from __future__ import annotations

import os
from dataclasses import dataclass

from core_engine.contract import resolve_dimension

DEFAULT_EMBED_MODEL = "text-embedding-3-small"


def _env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


@dataclass(frozen=True)
class HaystackSettings:
    embed_dimension: int = resolve_dimension(DEFAULT_EMBED_MODEL)
    parent_max_words: int = 220
    child_max_words: int = 90
    child_overlap_words: int = 15
    top_k_candidates: int = 20
    rerank_top_k: int = 3
    rerank_threshold: float = 0.7


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw and raw.strip() else default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw and raw.strip() else default


def load_settings() -> HaystackSettings:
    provider_mode = os.getenv("AI_PROVIDER", "auto").strip().lower()
    has_real_provider = bool(_env("EMBED_API_KEY", "OPENAI_API_KEY") or _env("EMBED_BASE_URL"))
    embed_model = (
        "offline"
        if provider_mode == "offline" or (provider_mode == "auto" and not has_real_provider)
        else os.getenv("EMBED_MODEL", DEFAULT_EMBED_MODEL)
    )
    raw_dim = os.getenv("EMBED_DIMENSION")
    override = int(raw_dim) if raw_dim and raw_dim.strip() else None
    return HaystackSettings(
        embed_dimension=resolve_dimension(embed_model, override),
        parent_max_words=_int("SECTION_MAX_WORDS", 220),
        child_max_words=_int("CHILD_MAX_WORDS", 90),
        child_overlap_words=_int("CHILD_OVERLAP_WORDS", 15),
        top_k_candidates=_int("SEARCH_TOP_K", 20),
        rerank_top_k=_int("RERANK_TOP_K", 3),
        rerank_threshold=_float("RERANK_THRESHOLD", 0.7),
    )
