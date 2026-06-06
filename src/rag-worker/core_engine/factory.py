"""Composition root - wire ingest engine from settings + AI provider + vector config.

Two independent config axes meet here:
- AI provider (`core_engine.ai`) decides embed/caption/rerank behavior.
- `VectorStoreConfig` decides vector database provider + deployment.

Factory forces store dimension = embedder dimension (ingest==query==store, search.md §2).
"""

from __future__ import annotations

import os

from core_engine.ai import AIProvider, get_ai_provider
from core_engine.config import HaystackSettings, load_settings
from core_engine.config_schema import (
    CaptionerConfig,
    ChunkerConfig,
    CommonConfig,
    EmbedderConfig,
    ParserConfig,
    PipelineConfig,
    VectorStoreConfigModel,
)
from core_engine.engine import HaystackRagEngine
from core_engine.mapping import build_engine_from_config
from core_engine.vectorstore import VectorStoreConfig

_TRUTHY_ENV = frozenset({"1", "true", "yes", "on"})
_FALSY_ENV = frozenset({"0", "false", "no", "off"})


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


def _resolve_caption_enabled(caption: bool | None) -> bool:
    return caption if caption is not None else caption_enabled_from_env()


def _wire(
    settings: HaystackSettings,
    provider: AIProvider,
    vector_config: VectorStoreConfig | None,
    dim: int,
    *,
    caption: bool | None,
) -> HaystackRagEngine:
    resolved_caption = _resolve_caption_enabled(caption)
    resolved_vector_config = vector_config or VectorStoreConfig.from_env(dimension=dim)
    embed_model_override = provider.embed_model_override
    if embed_model_override is not None:
        resolved_vector_config = (
            resolved_vector_config.with_embed_model(embed_model_override).with_dimension(dim)
        )
    cfg = PipelineConfig(
        common=CommonConfig(
            ai_mode=provider.name,
        ),
        embedder=EmbedderConfig(
            model=resolved_vector_config.embed_model,
            dimension=dim,
        ),
        captioner=CaptionerConfig(
            impl="provider" if resolved_caption else "none",
            model="gpt-4o-mini",
        ),
        parser=ParserConfig(impl="local", params={"max_workers": 2}),
        chunker=ChunkerConfig(
            impl="heading_sections",
            params={
                "parent_max_words": settings.parent_max_words,
                "child_max_words": settings.child_max_words,
                "child_overlap_words": settings.child_overlap_words,
            },
        ),
        vector_store=VectorStoreConfigModel(
            impl=resolved_vector_config.provider,
            params={
                "collection": resolved_vector_config.collection,
                "url": resolved_vector_config.url,
                "api_key": resolved_vector_config.api_key,
            },
        ),
    )
    return build_engine_from_config(
        cfg,
        provider=provider,
        dim=dim,
        vector_config_override=resolved_vector_config,
    )


def build_engine(
    settings: HaystackSettings | None = None,
    provider: AIProvider | None = None,
    *,
    caption: bool | None = None,
    vector_config: VectorStoreConfig | None = None,
) -> HaystackRagEngine:
    """Wire engine without needing network access."""
    provider = provider or get_ai_provider()
    settings = settings or load_settings()
    dim = (
        provider.fixed_dimension
        if provider.fixed_dimension is not None
        else settings.embed_dimension
    )
    return _wire(settings, provider, vector_config, dim, caption=caption)


async def build_engine_probe(
    settings: HaystackSettings | None = None,
    provider: AIProvider | None = None,
    *,
    caption: bool | None = None,
    vector_config: VectorStoreConfig | None = None,
) -> HaystackRagEngine:
    """Like build_engine, but probes the real dimension from an OpenAI model."""
    provider = provider or get_ai_provider()
    settings = settings or load_settings()
    if provider.fixed_dimension is not None:
        dim = provider.fixed_dimension
    elif provider.name == "openai":
        dim = await provider.probe_dimension()
    else:
        dim = settings.embed_dimension
    return _wire(settings, provider, vector_config, dim, caption=caption)
