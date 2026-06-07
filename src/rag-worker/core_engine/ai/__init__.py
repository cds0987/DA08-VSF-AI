"""AI gateway for all outbound AI calls."""

from __future__ import annotations

from typing import Optional

from core_engine.ai.base import (
    AIProvider,
    AIError,
    AISettings,
    CAPTION,
    EMBED,
    OCR,
    PermanentAIError,
    RERANK,
    RERANK_QUERY_MARKER,
    TransientAIError,
    CapabilityConfig,
    VisionImage,
    load_ai_settings,
    retry_async,
)
from core_engine.ai.offline_provider import DEFAULT_DIM, OfflineProvider

_provider: Optional[AIProvider] = None


def _build_provider(settings: AISettings | None = None) -> AIProvider:
    s = settings or load_ai_settings()
    mode = s.provider
    if mode == "auto":
        has_real = bool(s.embed.api_key or s.embed.base_url)
        mode = "openai" if has_real else "offline"
    if mode == "openai":
        from core_engine.ai.openai_provider import OpenAIProvider

        provider = OpenAIProvider(s)
        provider.validate()
        return provider
    if mode == "offline":
        return OfflineProvider(s.embed_dimension or DEFAULT_DIM)
    raise ValueError(f"AI_PROVIDER khong hop le: {mode!r} (auto|openai|offline)")


def build_provider(settings: AISettings | None = None) -> AIProvider:
    return _build_provider(settings)


def get_ai_provider() -> AIProvider:
    global _provider
    if _provider is None:
        _provider = _build_provider()
    return _provider


def set_ai_provider(provider: AIProvider) -> None:
    global _provider
    _provider = provider


def reset_ai_provider() -> None:
    global _provider
    _provider = None


def __getattr__(name: str):
    if name == "OpenAIProvider":
        from core_engine.ai.openai_provider import OpenAIProvider

        return OpenAIProvider
    raise AttributeError(name)


__all__ = [
    "AIProvider",
    "AIError",
    "AISettings",
    "CapabilityConfig",
    "VisionImage",
    "EMBED",
    "CAPTION",
    "RERANK",
    "OCR",
    "RERANK_QUERY_MARKER",
    "load_ai_settings",
    "retry_async",
    "build_provider",
    "OpenAIProvider",
    "OfflineProvider",
    "PermanentAIError",
    "TransientAIError",
    "get_ai_provider",
    "set_ai_provider",
    "reset_ai_provider",
]
