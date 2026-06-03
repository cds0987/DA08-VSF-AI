"""AI gateway — điểm vào DUY NHẤT cho mọi outbound AI call của rag-service.

    from haystack_interface.ai import get_ai_provider
    provider = get_ai_provider()
    vecs = await provider.embed(["..."])
    txt  = await provider.chat("...", capability="caption")

Một singleton dùng chung (embedding.md §0: một service chung đảm-bảo-bằng-kiến-trúc
rằng ingest & query cùng embedder/dimension). Đổi provider runtime/test qua
`set_ai_provider`; `auto` chọn OpenAI khi có key/base_url, ngược lại Offline.
"""

from __future__ import annotations

from typing import Optional

from haystack_interface.ai.base import (
    AIProvider,
    AISettings,
    CapabilityConfig,
    CAPTION,
    EMBED,
    RERANK,
    load_ai_settings,
    retry_async,
)
from haystack_interface.ai.offline_provider import OfflineProvider, DEFAULT_DIM
from haystack_interface.ai.openai_provider import OpenAIProvider

_provider: Optional[AIProvider] = None


def _build_provider(settings: AISettings | None = None) -> AIProvider:
    s = settings or load_ai_settings()
    mode = s.provider
    if mode == "auto":
        has_real = bool(s.embed.api_key or s.embed.base_url)
        mode = "openai" if has_real else "offline"
    if mode == "openai":
        provider = OpenAIProvider(s)
        provider.validate()                 # fail-fast (embedding.md §4)
        return provider
    if mode == "offline":
        return OfflineProvider(s.embed_dimension or DEFAULT_DIM)
    raise ValueError(f"AI_PROVIDER không hợp lệ: {mode!r} (auto|openai|offline)")


def get_ai_provider() -> AIProvider:
    """Trả singleton AI provider (lazy-init từ env lần đầu)."""
    global _provider
    if _provider is None:
        _provider = _build_provider()
    return _provider


def set_ai_provider(provider: AIProvider) -> None:
    """Ép provider cụ thể (test / chuyển đổi runtime)."""
    global _provider
    _provider = provider


def reset_ai_provider() -> None:
    """Xoá singleton để lần gọi sau init lại từ env."""
    global _provider
    _provider = None


__all__ = [
    "AIProvider",
    "AISettings",
    "CapabilityConfig",
    "EMBED",
    "CAPTION",
    "RERANK",
    "load_ai_settings",
    "retry_async",
    "OpenAIProvider",
    "OfflineProvider",
    "get_ai_provider",
    "set_ai_provider",
    "reset_ai_provider",
]
