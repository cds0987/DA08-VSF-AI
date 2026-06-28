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

import hashlib
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

# Ghi multi-collection 2 chế độ:
#   replicate (mặc định) -> mỗi doc embed vào MỌI collection (5/5) — backward compat.
#   shard     -> mỗi doc embed vào CHỈ 1 collection chọn round-robin theo doc-id
#                (hash(document_id) % pool) => corpus chia đều ~N/5 -> throughput ×5.
EMBED_MODE_REPLICATE = "replicate"
EMBED_MODE_SHARD = "shard"
_VALID_EMBED_MODES = {EMBED_MODE_REPLICATE, EMBED_MODE_SHARD}


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


def load_embed_mode(path: str | os.PathLike[str] | None = None) -> str:
    """Đọc embeddings.yaml -> chế độ ghi (`replicate` mặc định | `shard`).

    File thiếu / field thiếu / giá trị lạ -> replicate (AN TOÀN, giữ hành vi cũ). Có thể
    override bằng env MULTI_EMBED_MODE (ưu tiên cao hơn yaml) cho thử nghiệm/rollback nhanh.
    """
    env_mode = os.getenv("MULTI_EMBED_MODE", "").strip().lower()
    if env_mode in _VALID_EMBED_MODES:
        return env_mode
    cfg_path = Path(path) if path is not None else embeddings_config_path()
    if not cfg_path.is_file():
        return EMBED_MODE_REPLICATE
    payload = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    mode = str(payload.get("mode", EMBED_MODE_REPLICATE)).strip().lower()
    return mode if mode in _VALID_EMBED_MODES else EMBED_MODE_REPLICATE


def select_shard_index(document_id: str | None, pool_size: int) -> int:
    """Chọn slot shard cho 1 doc: hash(document_id) % pool_size — DETERMINISTIC + đều.

    Cùng document_id -> CÙNG slot (re-ingest idempotent, doc đi đúng collection cũ).
    Dùng SHA-1 (KHÔNG dùng builtin hash() — PYTHONHASHSEED ngẫu nhiên hoá str hash giữa
    các process -> mất tính ổn định). document_id rỗng/None -> slot 0 (fallback primary,
    KHÔNG crash). pool_size<=0 -> 0.
    """
    if pool_size <= 0:
        return 0
    doc = (document_id or "").strip()
    if not doc:
        return 0
    digest = hashlib.sha1(doc.encode("utf-8")).hexdigest()
    return int(digest, 16) % pool_size


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
        targets.append(_build_target(model, dim, cfg))
    return targets


def _build_target(model: str, dim: int, cfg: VectorStoreConfig) -> EmbedTarget:
    from core_engine.embedding import ProviderEmbeddingService

    provider = _provider_for_model(model, dim)
    return EmbedTarget(
        embed_model=model,
        dimension=dim,
        config=cfg,
        embedder=ProviderEmbeddingService(provider, dimension=dim),
        vectors=build_vector_repository(cfg),
    )


def build_read_targets(
    base_config: VectorStoreConfig,
    *,
    models: List[str] | None = None,
) -> List[EmbedTarget]:
    """Dựng tập EmbedTarget cho READ shard-merge: 1 target / collection của MỌI model active
    (GỒM CẢ primary — đối xứng với pool ghi shard). Mỗi target tự embed query bằng model
    của nó -> search ĐÚNG vector space của collection đó. Dedup theo index_id (collection).
    """
    active = models if models is not None else load_active_embed_models()
    return [_build_target(model, dim, cfg) for model, dim, cfg in resolve_target_configs(base_config, active)]
