"""Load cấu hình mcp-service từ config.yaml + env. BẢN RIÊNG (không dùng rag-worker).

mcp-service = THIN search interface: embed + vector search đã chuyển sang rag-worker
(POST /api/search). mcp KHÔNG còn biết embed model/collection/contract — chỉ giữ:
- rag_worker_url + search_timeout: gọi rag-worker.
- reranker + retrieval: rerank + diversify ứng viên trả về.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

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
    # rag-worker /api/search (embed + vector search ĐÃ chuyển sang rag-worker).
    rag_worker_url: str
    search_timeout_seconds: float
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
    tools_profile: Mapping[str, Any] = field(default_factory=dict)

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


def load_settings(path: str | os.PathLike[str] | None = None) -> McpSettings:
    config_path = Path(path) if path else DEFAULT_CONFIG
    raw = _resolve(yaml.safe_load(config_path.read_text(encoding="utf-8")) or {})
    profile = _active_profile(raw)

    server = profile.get("server") or {}
    # Mọi config của tool rag_search nest trong section `rag_search`; fallback về
    # top-level để tương thích ngược config cũ.
    rag_search_cfg = profile.get("rag_search") or {}
    search = rag_search_cfg.get("search") or profile.get("search") or {}
    reranker = rag_search_cfg.get("reranker") or profile.get("reranker") or {}
    retrieval = rag_search_cfg.get("retrieval") or profile.get("retrieval") or {}

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
        rag_worker_url=str(search.get("rag_worker_url") or "http://rag-worker:8000").strip()
        or "http://rag-worker:8000",
        search_timeout_seconds=_float(search.get("timeout_seconds"), 30.0),
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
        tools_profile=profile,
    )
