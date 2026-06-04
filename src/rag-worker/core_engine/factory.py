"""Composition root - wire HaystackRagEngine from settings + AI provider + vector config.

Two independent config axes meet here:
- AI provider (`core_engine.ai`) decides embed/caption/rerank behavior.
- `VectorStoreConfig` decides vector database provider + deployment.

Factory forces store dimension = embedder dimension (ingest==query==store, search.md §2).
"""

from __future__ import annotations

from dataclasses import replace
import os
from typing import Optional

from core_engine.ai import AIProvider, get_ai_provider
from core_engine.ai.offline_provider import OfflineProvider
from core_engine.caption import ProviderCaptioner
from core_engine.config import HaystackSettings, load_settings
from core_engine.embedding import ProviderEmbeddingService
from core_engine.engine import HaystackRagEngine
from core_engine.rerank import (
    LLMReranker,
    LexicalRerankerService,
    NoopRerankerService,
    Reranker,
)
from core_engine.vectorstore import VectorStoreConfig, build_vector_repository

_TRUTHY_ENV = frozenset({"1", "true", "yes", "on"})
_FALSY_ENV = frozenset({"0", "false", "no", "off"})
_ALLOWED_RERANK_PROVIDERS = frozenset({"llm", "lexical", "none"})


def _parse_bool_env(name: str, *, default: bool) -> bool:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    normalized = raw.lower()
    if normalized in _TRUTHY_ENV:
        return True
    if normalized in _FALSY_ENV:
        return False
    raise ValueError(
        f"{name} must be one of {sorted(_TRUTHY_ENV | _FALSY_ENV)} when configured"
    )


def caption_enabled_from_env() -> bool:
    return _parse_bool_env("CAPTION_ENABLED", default=True)


def rerank_provider_from_env() -> str:
    raw = os.getenv("RERANK_PROVIDER", "").strip().lower() or "llm"
    if raw not in _ALLOWED_RERANK_PROVIDERS:
        raise ValueError("RERANK_PROVIDER must be one of llm, lexical, none")
    return raw


def _resolve_caption_enabled(caption: bool | None) -> bool:
    return caption if caption is not None else caption_enabled_from_env()


def _resolve_reranker(provider: AIProvider, reranker: Optional[Reranker]) -> Reranker:
    if reranker is not None:
        return reranker
    match rerank_provider_from_env():
        case "llm":
            return LLMReranker(provider)
        case "lexical":
            return LexicalRerankerService()
        case "none":
            return NoopRerankerService()
    raise AssertionError("unreachable rerank provider")


def _wire(
    settings: HaystackSettings,
    provider: AIProvider,
    vector_config: Optional[VectorStoreConfig],
    dim: int,
    *,
    caption: bool | None,
    reranker: Optional[Reranker],
) -> HaystackRagEngine:
    settings = replace(settings, embed_dimension=dim)
    vs_config = (vector_config or VectorStoreConfig.from_env()).with_dimension(dim)
    resolved_caption = _resolve_caption_enabled(caption)
    return HaystackRagEngine(
        settings=settings,
        embedder=ProviderEmbeddingService(provider, dimension=dim),
        vectors=build_vector_repository(vs_config),
        reranker=_resolve_reranker(provider, reranker),
        captioner=ProviderCaptioner(provider) if resolved_caption else None,
    )


def build_engine(
    settings: HaystackSettings | None = None,
    provider: AIProvider | None = None,
    *,
    caption: bool | None = None,
    reranker: Optional[Reranker] = None,
    vector_config: Optional[VectorStoreConfig] = None,
) -> HaystackRagEngine:
    """Wire engine without needing network access."""
    provider = provider or get_ai_provider()
    settings = settings or load_settings()
    dim = (
        provider.dimension
        if isinstance(provider, OfflineProvider)
        else settings.embed_dimension
    )
    return _wire(settings, provider, vector_config, dim, caption=caption, reranker=reranker)


async def build_engine_probe(
    settings: HaystackSettings | None = None,
    provider: AIProvider | None = None,
    *,
    caption: bool | None = None,
    reranker: Optional[Reranker] = None,
    vector_config: Optional[VectorStoreConfig] = None,
) -> HaystackRagEngine:
    """Like build_engine, but probes the real dimension from an OpenAI model."""
    provider = provider or get_ai_provider()
    settings = settings or load_settings()
    if provider.name == "openai":
        dim = await provider.probe_dimension()
    elif isinstance(provider, OfflineProvider):
        dim = provider.dimension
    else:
        dim = settings.embed_dimension
    return _wire(settings, provider, vector_config, dim, caption=caption, reranker=reranker)
