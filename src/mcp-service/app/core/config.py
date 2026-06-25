"""Load cấu hình mcp-service từ config.yaml + env. BẢN RIÊNG (không dùng rag-worker).

Resolve embed_model/dimension theo CÙNG quy tắc rag-worker để fingerprint khớp:
- ai_mode=offline (hoặc auto mà không có key) -> embed_model = "offline"
- ngược lại -> embedder.model
- dimension = derive từ model (override qua EMBED_DIMENSION nếu hợp lệ)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from app.core.contract import (
    SPARSE_ENCODING_VERSION,
    ResolvedVectorstoreContract,
    resolve_vectorstore_contract,
)

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config.yaml"

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}")


def _expand(value: str) -> str:
    def repl(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        return os.getenv(name) or (default if default is not None else "")

    return _ENV_PATTERN.sub(repl, value)


def _resolve(node: Any) -> Any:
    if isinstance(node, str):
        return _expand(node)
    if isinstance(node, dict):
        return {key: _resolve(val) for key, val in node.items()}
    if isinstance(node, list):
        return [_resolve(item) for item in node]
    return node


def _active_profile(raw: dict) -> dict:
    profiles = raw.get("profiles") or {}
    active = str(raw.get("active") or "baseline").strip() or "baseline"
    profile = profiles.get(active)
    if profile is None:
        raise ValueError(f"profile {active!r} không có trong config.yaml")
    extends = profile.get("extends")
    if extends:
        base = dict(profiles.get(extends) or {})
        base.update({k: v for k, v in profile.items() if k != "extends"})
        return base
    return profile


def _has_real_provider() -> bool:
    return bool(
        (os.getenv("EMBED_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
        or (os.getenv("EMBED_BASE_URL") or "").strip()
    )


@dataclass(frozen=True)
class ToolSpec:
    enabled: bool
    # `enabled` có được khai tường minh trong config không. False = không có key
    # `enabled` cho tool này → build_mcp áp default theo nguồn tool (built-in vs
    # entry-point bên thứ ba).
    enabled_explicit: bool = False
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class McpSettings:
    host: str
    port: int
    log_level: str
    app_env: str
    internal_token: str
    provider: str
    collection: str
    embed_model: str
    dimension: int
    url: str
    api_key: str
    embed_base_url: str
    embed_api_key: str
    rerank_impl: str
    rerank_model: str
    rerank_base_url: str
    rerank_api_key: str
    rerank_timeout_seconds: float
    rerank_batch_size: int
    rerank_passage_chars: int
    top_k_candidates: int
    rerank_top_k: int
    rerank_threshold: float
    # Đa dạng document trong kết quả rerank: tối đa N chunk/doc -> chống "1 doc thống trị top-k"
    # (chôn doc nhỏ + giảm precision cross-doc). 0 = TẮT (giữ hành vi cũ). pool = nhân final_k để
    # rerank rộng hơn rồi chọn đa dạng.
    rerank_max_per_doc: int = 0
    rerank_diversity_pool: int = 3
    # Graceful fallback: router (embed_base_url) down -> gọi THẲNG OpenAI bằng key dự phòng.
    # Trống = TẮT (giữ hành vi cũ). Bật khi flip embed_base_url -> ai-router để search KHÔNG sập.
    embed_fallback_base_url: str = ""
    embed_fallback_api_key: str = ""
    # EMBED COALESCER (fix embed-storm @150: 611 embed call -> gom thành batch). Gom embed() đồng
    # thời (cửa sổ window_ms / tới max) -> 1 call embeddings.create(input=[...]). False = per-call cũ.
    embed_coalesce: bool = True
    embed_coalesce_max: int = 128          # CAP batch (thực = min arrivals-trong-window, cap)
    embed_coalesce_window_ms: int = 20     # cửa sổ gom (~0 so với embed ~1.7s)
    basic_auth: str = ""
    timeout: int | None = None
    options: Mapping[str, Any] = field(default_factory=dict)
    tools_profile: Mapping[str, Any] = field(default_factory=dict)
    # hybrid (BM25) -> contract trỏ collection __s{ver}. PHẢI khớp rag-worker VECTOR_HYBRID,
    # nếu không mcp đọc collection khác producer ghi -> 0 sources. Detect schema query vẫn
    # độc lập (dense/hybrid) — cờ này CHỈ quyết định TÊN collection (sparse_version).
    hybrid: bool = False

    @property
    def sparse_version(self) -> int:
        return SPARSE_ENCODING_VERSION if self.hybrid else 0

    def contract(self) -> ResolvedVectorstoreContract:
        return resolve_vectorstore_contract(
            provider=self.provider,
            collection=self.collection,
            embed_model=self.embed_model,
            dimension=self.dimension,
            sparse_version=self.sparse_version,
        )

    @property
    def deployment(self) -> str:
        return "remote" if self.url else "in_process"

    @property
    def auth_enabled(self) -> bool:
        return bool(self.internal_token.strip())

    def tool_spec(self, name: str) -> ToolSpec:
        node = self.tools_profile.get(name) or {}
        enabled_explicit = "enabled" in node
        enabled_raw = str(node.get("enabled", "1")).strip().lower()
        params = {key: value for key, value in node.items() if key != "enabled"}
        return ToolSpec(
            enabled=enabled_raw in {"1", "true", "yes", "on"},
            enabled_explicit=enabled_explicit,
            params=params,
        )


def _resolved_embed_model(common: dict, embedder: dict) -> str:
    ai_mode = str((common.get("ai_mode") or "auto")).strip().lower()
    declared = str(embedder.get("model") or "text-embedding-3-small")
    if ai_mode == "offline" or (ai_mode == "auto" and not _has_real_provider()):
        return "offline"
    return declared


def load_settings(path: str | os.PathLike[str] | None = None) -> McpSettings:
    config_path = Path(path) if path else DEFAULT_CONFIG
    raw = _resolve(yaml.safe_load(config_path.read_text(encoding="utf-8")) or {})
    profile = _active_profile(raw)

    server = profile.get("server") or {}
    common = profile.get("common") or {}
    # Mọi config của tool rag_search nest trong section `rag_search`; fallback về
    # top-level để tương thích ngược config cũ.
    rag_search_cfg = profile.get("rag_search") or {}
    embedder = rag_search_cfg.get("embedder") or profile.get("embedder") or {}
    vector_store = rag_search_cfg.get("vector_store") or profile.get("vector_store") or {}
    params = vector_store.get("params") or {}
    reranker = rag_search_cfg.get("reranker") or profile.get("reranker") or {}
    retrieval = rag_search_cfg.get("retrieval") or profile.get("retrieval") or {}

    dim_raw = str(embedder.get("dimension") or "").strip()
    override = int(dim_raw) if dim_raw else None
    embed_model = _resolved_embed_model(common, embedder)
    contract = resolve_vectorstore_contract(
        provider=str(vector_store.get("impl") or "qdrant"),
        collection=str(params.get("collection") or "rag_chatbot"),
        embed_model=embed_model,
        dimension=override,
    )

    def _int(value: Any, default: int) -> int:
        text = str(value or "").strip()
        return int(text) if text else default

    def _float(value: Any, default: float) -> float:
        text = str(value or "").strip()
        return float(text) if text else default

    return McpSettings(
        host=str(server.get("host") or "0.0.0.0").strip() or "0.0.0.0",
        port=_int(server.get("port"), 8003),
        log_level=str(server.get("log_level") or "INFO").strip() or "INFO",
        app_env=str(server.get("app_env") or "development").strip().lower() or "development",
        internal_token=str(server.get("internal_token") or "").strip(),
        provider=contract.provider,
        collection=contract.collection,
        embed_model=contract.embed_model,
        dimension=contract.dimension,
        url=str(params.get("url") or "").strip(),
        api_key=str(params.get("api_key") or "").strip(),
        basic_auth=str(params.get("basic_auth") or "").strip(),
        timeout=(int(str(params.get("timeout")).strip()) if str(params.get("timeout") or "").strip() else None),
        embed_base_url=str(embedder.get("base_url") or "").strip(),
        embed_api_key=str(embedder.get("api_key") or "").strip(),
        embed_fallback_base_url=str(embedder.get("fallback_base_url") or "").strip(),
        embed_fallback_api_key=str(embedder.get("fallback_api_key") or "").strip(),
        rerank_impl=str(reranker.get("impl") or "none").strip().lower(),
        rerank_model=str(reranker.get("model") or "").strip(),
        rerank_base_url=str(reranker.get("base_url") or "").strip(),
        rerank_api_key=str(reranker.get("api_key") or "").strip(),
        rerank_timeout_seconds=_float(reranker.get("timeout_seconds"), 30.0),
        rerank_batch_size=_int((reranker.get("params") or {}).get("batch_size"), 8),
        rerank_passage_chars=_int((reranker.get("params") or {}).get("passage_chars"), 800),
        top_k_candidates=_int(retrieval.get("top_k_candidates"), 20),
        rerank_top_k=_int(retrieval.get("rerank_top_k"), 3),
        rerank_threshold=_float(retrieval.get("rerank_threshold"), 0.7),
        rerank_max_per_doc=_int(retrieval.get("rerank_max_per_doc"), 0),
        rerank_diversity_pool=_int(retrieval.get("rerank_diversity_pool"), 3),
        # VECTOR_HYBRID PHẢI khớp rag-worker (env hoặc params.hybrid trong config.yaml) ->
        # contract trỏ đúng collection __s{ver}. Mặc định OFF (collection dense/schema cũ).
        hybrid=(
            str(os.getenv("VECTOR_HYBRID") or params.get("hybrid") or "")
            .strip().lower() in {"1", "true", "yes", "on"}
        ),
        tools_profile=profile,
    )
