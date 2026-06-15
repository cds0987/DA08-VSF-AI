"""Haystack settings for ingest stages."""

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
    # Cái gì được EMBED (vector dense) khi captioner bật:
    #   caption_raw (mặc định) = caption + raw child -> giữ literal (IP/mã/số) cho retrieve
    #   caption                = chỉ caption (hành vi cũ, dễ trượt câu hỏi tra-cứu-giá-trị)
    #   raw                    = chỉ raw child (bỏ cầu nối ngữ nghĩa của caption)
    # child_text (payload) LUÔN = raw child. Xem core_engine/engine.py build units.
    embed_target: str = "caption_raw"
    langfuse_enabled: bool = False
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://langfuse-web:3000"
    langfuse_sample_rate: float = 0.0
    langfuse_trace_on_error: bool = True
    # LangSmith ingest tracing — ĐỘC LẬP với langfuse + TÁCH project query-service.
    # project mặc định 'vsf-rag-ingest' (query-service dùng 'vsf-rag-chatbot') để phân biệt
    # luồng ingest với luồng query trên LangSmith. Thiếu API key -> tự tắt (no-op).
    langsmith_enabled: bool = False
    langsmith_api_key: str = ""
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_project: str = "vsf-rag-ingest"
    langsmith_sample_rate: float = 1.0
    langsmith_trace_on_error: bool = True


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw and raw.strip() else default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw and raw.strip() else default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if not raw or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


_EMBED_TARGETS = {"caption", "caption_raw", "raw"}


def _embed_target(raw: str | None) -> str:
    value = (raw or "").strip().lower()
    return value if value in _EMBED_TARGETS else "caption_raw"


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
        embed_target=_embed_target(os.getenv("EMBED_TARGET")),
        langfuse_enabled=_bool("LANGFUSE_ENABLED", False),
        langfuse_public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
        langfuse_secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
        langfuse_host=os.getenv("LANGFUSE_HOST", "http://langfuse-web:3000"),
        langfuse_sample_rate=_float("LANGFUSE_SAMPLE_RATE", 0.0),
        langfuse_trace_on_error=_bool("LANGFUSE_TRACE_ON_ERROR", True),
        langsmith_enabled=_bool("LANGSMITH_ENABLED", False),
        langsmith_api_key=os.getenv("LANGSMITH_API_KEY", ""),
        langsmith_endpoint=os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"),
        langsmith_project=os.getenv("LANGSMITH_PROJECT", "vsf-rag-ingest"),
        langsmith_sample_rate=_float("LANGSMITH_SAMPLE_RATE", 1.0),
        langsmith_trace_on_error=_bool("LANGSMITH_TRACE_ON_ERROR", True),
    )
