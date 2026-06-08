from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core_engine.ocr import ProviderImageTextExtractor

from core_engine.ai import AIProvider, AISettings, CapabilityConfig, build_provider
from core_engine.caption import ProviderCaptioner
from core_engine.chunking import SectionChunker
from core_engine.config import HaystackSettings
from core_engine.config_schema import PipelineConfig
from core_engine.contract import resolve_dimension
from core_engine.embedding import ProviderEmbeddingService
from core_engine.engine import HaystackRagEngine
from core_engine.registry import Registry
from core_engine.vectorstore import VectorStoreConfig, build_vector_repository

Factory = Callable[[Mapping[str, Any], "WireContext"], Any]
UNSET = object()

# Một Registry chung (core_engine.registry) cho mỗi component. Public API
# register/resolve giữ nguyên chữ ký (component, name) cho caller cũ + test, nhưng
# bookkeeping (guard trùng tên · liệt kê · entry-point discovery) dùng primitive
# dùng chung — đồng nhất với vectorstore + parser registry.
_REGISTRIES: dict[str, Registry[Factory]] = {}


def _registry_for(component: str) -> Registry[Factory]:
    reg = _REGISTRIES.get(component)
    if reg is None:
        reg = Registry(component, entry_point_group=f"rag_worker.{component}")
        _REGISTRIES[component] = reg
    return reg


@dataclass(frozen=True)
class WireContext:
    provider: AIProvider
    dim: int
    ocr_extractor: ProviderImageTextExtractor


def register(
    component: str,
    name: str,
    factory: Factory,
    *,
    override: bool = False,
) -> None:
    _registry_for(component).register(name, factory, override=override)


def resolve(component: str, stage_cfg: Any, ctx: WireContext) -> Any:
    impl = getattr(stage_cfg, "impl", None)
    params = getattr(stage_cfg, "params", {})
    factory = _registry_for(component).get(impl)
    return factory(dict(params or {}), ctx)


def _effective_embed_model(cfg: PipelineConfig) -> str:
    if cfg.common.ai_mode == "offline":
        return "offline"
    if cfg.common.ai_mode == "auto" and not (cfg.embedder.api_key or cfg.embedder.base_url):
        return "offline"
    return cfg.embedder.model


def build_ai_settings(cfg: PipelineConfig) -> AISettings:
    effective_model = _effective_embed_model(cfg)
    resolved_dim = resolve_dimension(effective_model, cfg.embedder.dimension)
    embed = CapabilityConfig(
        base_url=cfg.embedder.base_url or None,
        api_key=cfg.embedder.api_key,
        model=effective_model,
    )
    caption = CapabilityConfig(
        base_url=(cfg.captioner.base_url or cfg.embedder.base_url) or None,
        api_key=cfg.captioner.api_key or cfg.embedder.api_key,
        model=cfg.captioner.model,
    )
    ocr_model = cfg.parser.ocr.model if cfg.parser.ocr is not None else ""
    ocr = CapabilityConfig(
        base_url=(
            (cfg.parser.ocr.base_url if cfg.parser.ocr is not None else "")
            or caption.base_url
        )
        or None,
        api_key=(cfg.parser.ocr.api_key if cfg.parser.ocr is not None else "") or caption.api_key,
        model=ocr_model or caption.model,
    )
    return AISettings(
        embed=embed,
        caption=caption,
        ocr=ocr,
        embed_dimension=resolved_dim,
        max_retries=cfg.common.max_retries,
        timeout=cfg.common.timeout,
        provider=cfg.common.ai_mode,
    )


def build_ai_provider(cfg: PipelineConfig) -> AIProvider:
    return build_provider(build_ai_settings(cfg))


def to_settings(cfg: PipelineConfig, *, dim: int) -> HaystackSettings:
    return HaystackSettings(
        embed_dimension=dim,
        parent_max_words=int(cfg.chunker.params.get("parent_max_words", 220)),
        child_max_words=int(cfg.chunker.params.get("child_max_words", 90)),
        child_overlap_words=int(cfg.chunker.params.get("child_overlap_words", 15)),
    )


def to_vector_store_config(
    cfg: PipelineConfig,
    *,
    dim: int,
    override: VectorStoreConfig | None = None,
) -> VectorStoreConfig:
    if override is not None:
        return override.with_dimension(dim)
    return VectorStoreConfig(
        provider=cfg.vector_store.impl,
        collection=str(cfg.vector_store.params.get("collection", "rag_chatbot")),
        embed_model=_effective_embed_model(cfg),
        dimension=dim,
        url=str(cfg.vector_store.params.get("url", "")),
        api_key=str(cfg.vector_store.params.get("api_key", "")),
        basic_auth=str(cfg.vector_store.params.get("basic_auth", "")),
    )


def build_engine_from_config(
    cfg: PipelineConfig,
    *,
    provider: AIProvider | None = None,
    dim: int | None = None,
    vector_config_override: VectorStoreConfig | None = None,
) -> HaystackRagEngine:
    provider = provider or build_ai_provider(cfg)
    resolved_dim = (
        dim
        if dim is not None
        else (
            provider.fixed_dimension
            if provider.fixed_dimension is not None
            else resolve_dimension(_effective_embed_model(cfg), cfg.embedder.dimension)
        )
    )
    # Lazy import: ocr (vision/OCR) chỉ cần cho INGEST. Để top-level sẽ kéo
    # core_engine.ocr vào mọi `import core_engine.*` → vỡ hygiene read-path (mcp
    # search KHÔNG được kéo dep ingest nặng). Xem docs/search-split-vectorstore-contract.md §4.3.
    from core_engine.ocr import ProviderImageTextExtractor

    ctx = WireContext(
        provider=provider,
        dim=resolved_dim,
        ocr_extractor=ProviderImageTextExtractor(provider),
    )
    vector_config = to_vector_store_config(
        cfg,
        dim=resolved_dim,
        override=vector_config_override,
    )
    return HaystackRagEngine(
        settings=to_settings(cfg, dim=resolved_dim),
        embedder=ProviderEmbeddingService(provider, dimension=resolved_dim),
        vectors=build_vector_repository(vector_config),
        captioner=resolve("captioner", cfg.captioner, ctx),
        chunker=resolve("chunker", cfg.chunker, ctx),
    )


register(
    "chunker",
    "heading_sections",
    lambda params, ctx: SectionChunker(
        parent_max_words=int(params.get("parent_max_words", 220)),
        child_max_words=int(params.get("child_max_words", 90)),
        child_overlap_words=int(params.get("child_overlap_words", 15)),
    ),
)
register("captioner", "provider", lambda params, ctx: ProviderCaptioner(ctx.provider, **params))
register("captioner", "none", lambda params, ctx: None)
