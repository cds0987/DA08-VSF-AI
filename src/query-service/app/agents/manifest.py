"""Đọc agents.yaml -> AgentsManifest. Kill-switch: mọi lỗi (file thiếu / YAML hỏng /
field sai) -> fallback an toàn về mode 'react' -> service KHÔNG vỡ, giữ flow cũ.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from app.agents.base import RoleSpec

logger = logging.getLogger(__name__)

DEFAULT_MANIFEST_PATH = Path(__file__).with_name("agents.yaml")
FALLBACK_MODE = "react"

Mode = Literal["react", "orchestrator_workers"]


@dataclass(frozen=True)
class MemoryConfig:
    impl: str = "recent_buffer"
    keep_recent: int = 4
    summarize_after: int = 8


@dataclass(frozen=True)
class AgentsManifest:
    mode: Mode = FALLBACK_MODE
    planner: str = "react"
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    roles: tuple[RoleSpec, ...] = ()
    max_replan: int = 1
    max_workers_per_level: int = 4
    worker_timeout_seconds: int = 30
    # verify_before_synthesize: chèn node verify (deepseek-pro "think 2") giữa join->synthesize.
    # Đủ -> synthesize; thiếu -> replan (trong max_replan). False = đi thẳng synthesize (cũ).
    verify_before_synthesize: bool = False

    def enabled_roles(self) -> tuple[RoleSpec, ...]:
        return tuple(r for r in self.roles if r.enabled)

    def role(self, name: str) -> RoleSpec | None:
        key = name.strip().lower()
        return next((r for r in self.roles if r.name.strip().lower() == key), None)


def _safe_load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        logger.error("PyYAML chưa cài -> manifest rỗng (fallback react)")
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            raise ValueError("agents.yaml root phải là mapping")
        return data
    except FileNotFoundError:
        logger.warning("agents.yaml không tồn tại tại %s -> fallback react", path)
        return {}
    except Exception as exc:  # noqa: BLE001 — manifest hỏng KHÔNG được làm vỡ service
        logger.error("agents.yaml lỗi (%s) -> fallback react: %s", path, exc)
        return {}


def _parse_roles(raw: Any) -> tuple[RoleSpec, ...]:
    if not isinstance(raw, list):
        return ()
    roles: list[RoleSpec] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("name"):
            logger.warning("role item không hợp lệ, bỏ qua: %r", item)
            continue
        tools = item.get("tools") or []
        roles.append(
            RoleSpec(
                name=str(item["name"]),
                capability=str(item.get("capability", "worker")),
                tools=tuple(str(t) for t in tools if t),
                enabled=bool(item.get("enabled", True)),
                description=str(item.get("description", "")),
            )
        )
    return tuple(roles)


@lru_cache(maxsize=1)
def load_manifest(path: str | None = None) -> AgentsManifest:
    """Load + parse agents.yaml. Cache 1 lần / process. Lỗi -> AgentsManifest mặc định (react)."""
    p = Path(path) if path else DEFAULT_MANIFEST_PATH
    data = _safe_load_yaml(p)
    if not data:
        return AgentsManifest()

    mode = str(data.get("mode", FALLBACK_MODE))
    if mode not in ("react", "orchestrator_workers"):
        logger.warning("mode=%r không hợp lệ -> fallback react", mode)
        mode = FALLBACK_MODE

    mem_raw = data.get("memory") or {}
    memory = MemoryConfig(
        impl=str(mem_raw.get("impl", "recent_buffer")),
        keep_recent=int(mem_raw.get("keep_recent", 4)),
        summarize_after=int(mem_raw.get("summarize_after", 8)),
    )

    return AgentsManifest(
        mode=mode,  # type: ignore[arg-type]
        planner=str(data.get("planner", "react")),
        memory=memory,
        roles=_parse_roles(data.get("roles")),
        max_replan=int(data.get("max_replan", 1)),
        max_workers_per_level=int(data.get("max_workers_per_level", 4)),
        worker_timeout_seconds=int(data.get("worker_timeout_seconds", 30)),
        verify_before_synthesize=bool(data.get("verify_before_synthesize", False)),
    )
