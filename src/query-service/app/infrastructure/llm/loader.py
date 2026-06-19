"""Đọc profiles.yaml -> NodeProfile cho từng node, resolve adapter qua registry.

Kill-switch: mọi lỗi (file thiếu / YAML hỏng / node thiếu / adapter chưa đăng ký) đều
fallback an toàn về adapter 'standard' + capability = tên node -> service KHÔNG vỡ.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from .base import NodeLLMAdapter
from .registry import get_adapter, is_registered

# Import side-effect: đăng ký mọi adapter trước khi resolve.
from . import adapters as _adapters  # noqa: F401

logger = logging.getLogger(__name__)

DEFAULT_PROFILES_PATH = Path(__file__).with_name("profiles.yaml")
FALLBACK_ADAPTER = "standard"


@dataclass(frozen=True)
class NodeProfile:
    """Cấu hình LLM đã resolve cho 1 node."""

    node: str
    adapter: str
    capability: str | None = None
    models: tuple[str, ...] = field(default_factory=tuple)
    reasoning_effort: str | None = None

    def make_adapter(self) -> NodeLLMAdapter:
        """Trả instance adapter. Adapter chưa đăng ký -> fallback 'standard' (logged)."""
        if not is_registered(self.adapter):
            logger.warning(
                "llm_profile_adapter_unregistered node=%s adapter=%s -> fallback %s",
                self.node, self.adapter, FALLBACK_ADAPTER,
            )
            return get_adapter(FALLBACK_ADAPTER)
        return get_adapter(self.adapter)


def _safe_load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError:  # pragma: no cover - PyYAML có trong requirements
        logger.error("PyYAML chưa cài -> dùng profiles rỗng (fallback standard)")
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            raise ValueError("profiles.yaml root phải là mapping")
        return data
    except FileNotFoundError:
        logger.warning("profiles.yaml không tồn tại tại %s -> fallback standard", path)
        return {}
    except Exception as exc:  # noqa: BLE001 — manifest hỏng KHÔNG được làm vỡ service
        logger.error("profiles.yaml lỗi (%s) -> fallback standard: %s", path, exc)
        return {}


def _coerce_models(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, (list, tuple)):
        return tuple(str(m) for m in raw if m)
    return ()


@lru_cache(maxsize=1)
def load_profiles(path: str | None = None) -> dict[str, NodeProfile]:
    """Load + parse manifest -> {node: NodeProfile}. Cache 1 lần / process."""
    p = Path(path) if path else DEFAULT_PROFILES_PATH
    data = _safe_load_yaml(p)

    defaults = data.get("defaults") or {}
    default_adapter = str(defaults.get("adapter", FALLBACK_ADAPTER) or FALLBACK_ADAPTER)
    default_effort = defaults.get("reasoning_effort")

    profiles: dict[str, NodeProfile] = {}
    for node, cfg in (data.get("nodes") or {}).items():
        cfg = cfg or {}
        adapter = str(cfg.get("adapter", default_adapter) or default_adapter)
        profiles[node] = NodeProfile(
            node=node,
            adapter=adapter,
            capability=cfg.get("capability") or node,
            models=_coerce_models(cfg.get("models")),
            reasoning_effort=cfg.get("reasoning_effort", default_effort),
        )
    return profiles


def get_node_profile(node: str, path: str | None = None) -> NodeProfile:
    """Profile cho 1 node. Node chưa khai báo -> default an toàn (standard, capability=node)."""
    profiles = load_profiles(path)
    prof = profiles.get(node)
    if prof is None:
        logger.warning("llm_profile_missing node=%s -> default standard", node)
        return NodeProfile(node=node, adapter=FALLBACK_ADAPTER, capability=node)
    return prof
