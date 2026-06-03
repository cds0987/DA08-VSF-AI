"""Composition root — wire HaystackRagEngine từ settings + AI provider.

Đây là CHỖ DUY NHẤT quyết định backend (offline vs OpenAI). Mọi capability
(embed/caption/rerank) lấy chung một provider singleton (`haystack_interface.ai`)
→ ingest & query đảm bảo cùng provider/model/dimension (search.md §2).

    from haystack_interface import build_engine
    engine = build_engine()                       # auto theo env
    engine = await build_engine_probe()            # OpenAI: probe dimension thật
"""

from __future__ import annotations

from typing import Optional

from haystack_interface.ai import AIProvider, get_ai_provider
from haystack_interface.ai.offline_provider import OfflineProvider
from haystack_interface.ai.openai_provider import OpenAIProvider
from haystack_interface.caption import ProviderCaptioner
from haystack_interface.config import HaystackSettings, load_settings
from haystack_interface.embedding import ProviderEmbeddingService
from haystack_interface.engine import HaystackRagEngine
from haystack_interface.rerank import LLMReranker, Reranker
from haystack_interface.vectorstore import InMemoryVectorRepository


def _wire(
    settings: HaystackSettings,
    provider: AIProvider,
    *,
    caption: bool,
    reranker: Optional[Reranker],
) -> HaystackRagEngine:
    embedder = ProviderEmbeddingService(provider, dimension=settings.embed_dimension)
    return HaystackRagEngine(
        settings=settings,
        embedder=embedder,
        vectors=InMemoryVectorRepository(settings),
        reranker=reranker or LLMReranker(provider),
        captioner=ProviderCaptioner(provider) if caption else None,
    )


def build_engine(
    settings: HaystackSettings | None = None,
    provider: AIProvider | None = None,
    *,
    caption: bool = True,
    reranker: Optional[Reranker] = None,
) -> HaystackRagEngine:
    """Wire engine không cần network.

    Dimension phải biết trước (không probe): offline → từ provider; OpenAI → từ
    `EMBED_DIMENSION`. Thiếu dimension cho OpenAI → dùng `build_engine_probe()`.
    """
    provider = provider or get_ai_provider()
    settings = settings or load_settings()

    if isinstance(provider, OfflineProvider):
        settings = _with_dim(settings, provider.dimension)
    return _wire(settings, provider, caption=caption, reranker=reranker)


async def build_engine_probe(
    settings: HaystackSettings | None = None,
    provider: AIProvider | None = None,
    *,
    caption: bool = True,
    reranker: Optional[Reranker] = None,
) -> HaystackRagEngine:
    """Như build_engine nhưng probe dimension thật từ OpenAI model (cần key/network)."""
    provider = provider or get_ai_provider()
    settings = settings or load_settings()
    if isinstance(provider, OpenAIProvider):
        settings = _with_dim(settings, await provider.probe_dimension())
    elif isinstance(provider, OfflineProvider):
        settings = _with_dim(settings, provider.dimension)
    return _wire(settings, provider, caption=caption, reranker=reranker)


def _with_dim(settings: HaystackSettings, dim: int) -> HaystackSettings:
    if settings.embed_dimension == dim:
        return settings
    return HaystackSettings(
        embed_dimension=dim,
        parent_max_words=settings.parent_max_words,
        child_max_words=settings.child_max_words,
        child_overlap_words=settings.child_overlap_words,
        top_k_candidates=settings.top_k_candidates,
        rerank_top_k=settings.rerank_top_k,
        rerank_threshold=settings.rerank_threshold,
        collection=settings.collection,
    )
