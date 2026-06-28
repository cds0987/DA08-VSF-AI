"""Multi-collection embed — đọc embeddings.yaml -> tập model active ghi song song.

Mỗi embed model active = 1 collection (index_id fingerprint encode model+dim). Ingest
embed CHUNG chunks (parse/OCR/caption 1 lần ở engine) rồi LOOP mọi model -> embed bằng
model đó -> upsert vào collection riêng. Append-migration: thêm model = thêm dòng yaml ->
collection mới tự tạo + backfill; bỏ model = ngừng ghi, KHÔNG xóa collection cũ.

Kiến trúc (KHÔNG bypass):
- Tận dụng VectorStoreConfig.with_embed_model + resolve_dimension (native) -> per-model config.
- Mỗi model 1 ProviderEmbeddingService + 1 VectorStore (build_vector_repository) như primary.
- Per-model AISettings = replace(embed.model) -> OpenAIProvider gửi model THẬT qua ai-router
  -> alias routing.yaml map về capability embed (đúng provider). Mọi call vẫn QUA AI Router.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import List

import yaml

from core_engine.ai import AIProvider, AISettings, load_ai_settings
from core_engine.contract import resolve_dimension
from core_engine.types import EmbeddingService, VectorRepository
from core_engine.vectorstore import VectorStoreConfig, build_vector_repository

DEFAULT_EMBEDDINGS_CONFIG = "embeddings.yaml"


@dataclass(frozen=True)
class EmbedTarget:
    """Một đích ghi: model + collection + embedder + vectorstore (độc lập với primary)."""

    embed_model: str
    dimension: int
    config: VectorStoreConfig
    embedder: EmbeddingService
    vectors: VectorRepository

    @property
    def collection(self) -> str:
        return self.config.index_id()


def embeddings_config_path() -> Path:
    return Path(os.getenv("EMBEDDINGS_CONFIG", DEFAULT_EMBEDDINGS_CONFIG))


def load_active_embed_models(path: str | os.PathLike[str] | None = None) -> List[str]:
    """Đọc embeddings.yaml -> danh sách model active (giữ thứ tự, bỏ trùng, normalize lower).

    File thiếu / rỗng -> [] (multi-collection tắt; chỉ ghi primary). Đây là DANH SÁCH GHI;
    primary (EMBED_MODEL) được caller gộp riêng để luôn ghi dù không liệt kê.
    """
    cfg_path = Path(path) if path is not None else embeddings_config_path()
    if not cfg_path.is_file():
        return []
    payload = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    raw = payload.get("embed_models") or []
    seen: set[str] = set()
    models: List[str] = []
    for item in raw:
        name = str(item).strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)
        models.append(name)
    return models


def resolve_target_configs(
    base_config: VectorStoreConfig,
    models: List[str],
) -> List[tuple[str, int, VectorStoreConfig]]:
    """(model, native_dim, per-model VectorStoreConfig) cho mỗi model active.

    dim = native theo contract (KHÔNG MRL override cho secondary — collection riêng,
    không ràng buộc vector-size hạ tầng của primary). Dedup theo index_id (collection):
    alias ngắn/đầy đủ CHUNG tag -> 1 collection -> ghi 1 lần.
    """
    out: List[tuple[str, int, VectorStoreConfig]] = []
    seen_collections: set[str] = set()
    for model in models:
        dim = resolve_dimension(model)
        cfg = base_config.with_embed_model(model).with_dimension(dim)
        collection = cfg.index_id()
        if collection in seen_collections:
            continue
        seen_collections.add(collection)
        out.append((model, dim, cfg))
    return out


def _provider_for_model(model: str, dimension: int) -> AIProvider:
    """OpenAIProvider với embed.model ÉP = model (gửi qua ai-router -> alias embed).

    Tái dùng env embed (base_url/api_key = ai-router) của settings hiện tại; chỉ thay
    model + dimension. KHÔNG dựng provider lạ -> mọi call vẫn qua AI Router.
    """
    from core_engine.ai.openai_provider import OpenAIProvider

    base: AISettings = load_ai_settings()
    embed_cap = replace(base.embed, model=model)
    settings = replace(base, embed=embed_cap, embed_dimension=dimension)
    return OpenAIProvider(settings)


def build_embed_targets(
    base_config: VectorStoreConfig,
    *,
    primary_model: str | None = None,
    models: List[str] | None = None,
) -> List[EmbedTarget]:
    """Dựng tập EmbedTarget SECONDARY (KHÔNG gồm primary).

    primary_model: model collection chính (đã ghi bởi engine primary) -> LOẠI khỏi tập
    secondary để không ghi đôi. models: override danh sách (mặc định đọc embeddings.yaml).
    """
    active = models if models is not None else load_active_embed_models()
    primary_collection = (
        base_config.with_embed_model(primary_model)
        .with_dimension(base_config.dimension)
        .index_id()
        if primary_model
        else base_config.index_id()
    )
    targets: List[EmbedTarget] = []
    for model, dim, cfg in resolve_target_configs(base_config, active):
        if cfg.index_id() == primary_collection:
            continue  # đã ghi bởi engine primary
        provider = _provider_for_model(model, dim)
        from core_engine.embedding import ProviderEmbeddingService

        targets.append(
            EmbedTarget(
                embed_model=model,
                dimension=dim,
                config=cfg,
                embedder=ProviderEmbeddingService(provider, dimension=dim),
                vectors=build_vector_repository(cfg),
            )
        )
    return targets
