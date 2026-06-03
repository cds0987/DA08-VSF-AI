"""Composition root — wire HaystackRagEngine từ settings + AI provider + vector config.

Hai trục cấu hình độc lập, gặp nhau ở đây:
- AI provider (`haystack_interface.ai`) quyết định embed/caption/rerank.
- `VectorStoreConfig` quyết định vector database (provider + deployment) — config object.

Factory ép **dimension của store = dimension của embedder** (ingest==query==store,
search.md §2) — bất biến đảm bảo bằng kiến trúc, không bằng kỷ luật.

    from haystack_interface import build_engine, VectorStoreConfig
    engine = build_engine()                                   # auto theo env
    engine = build_engine(vector_config=VectorStoreConfig(provider="qdrant",
                                                          url="http://localhost:6333"))  # url -> remote
    engine = await build_engine_probe()                        # OpenAI: probe dimension thật
"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

from haystack_interface.ai import AIProvider, get_ai_provider
from haystack_interface.ai.offline_provider import OfflineProvider
from haystack_interface.caption import ProviderCaptioner
from haystack_interface.config import HaystackSettings, load_settings
from haystack_interface.embedding import ProviderEmbeddingService
from haystack_interface.engine import HaystackRagEngine
from haystack_interface.rerank import LLMReranker, Reranker
from haystack_interface.vectorstore import VectorStoreConfig, build_vector_repository


def _wire(
    settings: HaystackSettings,
    provider: AIProvider,
    vector_config: Optional[VectorStoreConfig],
    dim: int,
    *,
    caption: bool,
    reranker: Optional[Reranker],
) -> HaystackRagEngine:
    settings = replace(settings, embed_dimension=dim)             # embedder dùng dim này
    # Config object quyết định database; dimension ÉP bằng embedder (bất biến).
    vs_config = (vector_config or VectorStoreConfig.from_env()).with_dimension(dim)
    return HaystackRagEngine(
        settings=settings,
        embedder=ProviderEmbeddingService(provider, dimension=dim),
        vectors=build_vector_repository(vs_config),
        reranker=reranker or LLMReranker(provider),
        captioner=ProviderCaptioner(provider) if caption else None,
    )


def build_engine(
    settings: HaystackSettings | None = None,
    provider: AIProvider | None = None,
    *,
    caption: bool = True,
    reranker: Optional[Reranker] = None,
    vector_config: Optional[VectorStoreConfig] = None,
) -> HaystackRagEngine:
    """Wire engine không cần network.

    Dimension biết trước (không probe): offline → từ provider; OpenAI → từ
    `EMBED_DIMENSION`. Thiếu dimension cho OpenAI → dùng `build_engine_probe()`.
    """
    provider = provider or get_ai_provider()
    settings = settings or load_settings()
    dim = provider.dimension if isinstance(provider, OfflineProvider) else settings.embed_dimension
    return _wire(settings, provider, vector_config, dim, caption=caption, reranker=reranker)


async def build_engine_probe(
    settings: HaystackSettings | None = None,
    provider: AIProvider | None = None,
    *,
    caption: bool = True,
    reranker: Optional[Reranker] = None,
    vector_config: Optional[VectorStoreConfig] = None,
) -> HaystackRagEngine:
    """Như build_engine nhưng probe dimension thật từ OpenAI model (cần key/network)."""
    provider = provider or get_ai_provider()
    settings = settings or load_settings()
    if provider.name == "openai":
        dim = await provider.probe_dimension()
    elif isinstance(provider, OfflineProvider):
        dim = provider.dimension
    else:
        dim = settings.embed_dimension
    return _wire(settings, provider, vector_config, dim, caption=caption, reranker=reranker)
