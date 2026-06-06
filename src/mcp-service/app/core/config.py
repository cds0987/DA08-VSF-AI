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

from app.core.contract import ResolvedVectorstoreContract, resolve_vectorstore_contract

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
    options: Mapping[str, Any] = field(default_factory=dict)

    def contract(self) -> ResolvedVectorstoreContract:
        return resolve_vectorstore_contract(
            provider=self.provider,
            collection=self.collection,
            embed_model=self.embed_model,
            dimension=self.dimension,
        )

    @property
    def deployment(self) -> str:
        return "remote" if self.url else "in_process"

    @property
    def auth_enabled(self) -> bool:
        return bool(self.internal_token.strip())


def _resolved_embed_model(profile: dict) -> str:
    ai_mode = str(((profile.get("common") or {}).get("ai_mode") or "auto")).strip().lower()
    declared = str((profile.get("embedder") or {}).get("model") or "text-embedding-3-small")
    if ai_mode == "offline" or (ai_mode == "auto" and not _has_real_provider()):
        return "offline"
    return declared


def load_settings(path: str | os.PathLike[str] | None = None) -> McpSettings:
    config_path = Path(path) if path else DEFAULT_CONFIG
    raw = _resolve(yaml.safe_load(config_path.read_text(encoding="utf-8")) or {})
    profile = _active_profile(raw)

    server = profile.get("server") or {}
    embedder = profile.get("embedder") or {}
    vector_store = profile.get("vector_store") or {}
    params = vector_store.get("params") or {}
    reranker = profile.get("reranker") or {}
    retrieval = profile.get("retrieval") or {}

    dim_raw = str(embedder.get("dimension") or "").strip()
    override = int(dim_raw) if dim_raw else None
    embed_model = _resolved_embed_model(profile)
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
        embed_base_url=str(embedder.get("base_url") or "").strip(),
        embed_api_key=str(embedder.get("api_key") or "").strip(),
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
    )
