"""Registry MOSA cho role-agent / planner / memory provider.

Mô phỏng src/mcp-service/app/tools/registry.py: built-in đăng ký bằng decorator,
plugin bên thứ ba auto-discover qua entry-points. Thêm 1 role mới = viết class
+ @register_agent("ten") trong roles/, KHÔNG sửa graph/manifest schema.
"""
from __future__ import annotations

import importlib.metadata
import logging
from typing import Callable, Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class Registry(Generic[T]):
    def __init__(self, label: str, *, entry_point_group: str | None = None) -> None:
        self._label = label
        self._group = entry_point_group
        self._factories: dict[str, T] = {}
        self._entry_point_names: set[str] = set()
        self._entry_points_loaded = False

    def is_entry_point(self, name: str) -> bool:
        """True nếu `name` nạp từ entry-point (plugin), không phải built-in register()."""
        self._ensure_entry_points()
        return name.strip().lower() in self._entry_point_names

    def register(self, name: str, factory: T, *, override: bool = False) -> T:
        key = name.strip().lower()
        if not key:
            raise ValueError(f"{self._label}: name rỗng")
        if key in self._factories and not override:
            raise ValueError(
                f"{self._label}:{name!r} đã đăng ký. Truyền override=True nếu cố ý thay thế."
            )
        self._factories[key] = factory
        return factory

    def get(self, name: str) -> T:
        self._ensure_entry_points()
        factory = self._factories.get(name.strip().lower())
        if factory is None:
            raise KeyError(
                f"{self._label}={name!r} chưa đăng ký. Có: {self.available()}"
            )
        return factory

    def has(self, name: str) -> bool:
        self._ensure_entry_points()
        return name.strip().lower() in self._factories

    def available(self) -> list[str]:
        self._ensure_entry_points()
        return sorted(self._factories)

    def _ensure_entry_points(self) -> None:
        if self._entry_points_loaded or not self._group:
            return
        self._entry_points_loaded = True
        try:
            eps = importlib.metadata.entry_points(group=self._group)
        except Exception as exc:  # noqa: BLE001 — discovery hỏng KHÔNG làm vỡ service
            logger.warning("entry_points(%s) lỗi: %s", self._group, exc)
            return
        for ep in eps:
            key = ep.name.strip().lower()
            if key in self._factories:
                continue
            try:
                self.register(ep.name, ep.load())
                self._entry_point_names.add(key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("nạp entry-point %s:%s lỗi: %s", self._label, ep.name, exc)


# --- Các registry toàn cục (mỗi loại cấu phần 1 instance) ---------------------
AGENT_REGISTRY: Registry = Registry("agent_role", entry_point_group="vsf.query.agents")
PLANNER_REGISTRY: Registry = Registry("planner", entry_point_group="vsf.query.planners")
MEMORY_REGISTRY: Registry = Registry("memory", entry_point_group="vsf.query.memory")


def register_agent(name: str) -> Callable[[T], T]:
    """Decorator đăng ký class role-agent vào AGENT_REGISTRY dưới `name`."""

    def _decorator(cls: T) -> T:
        AGENT_REGISTRY.register(name, cls)
        return cls

    return _decorator


def register_planner(name: str) -> Callable[[T], T]:
    def _decorator(cls: T) -> T:
        PLANNER_REGISTRY.register(name, cls)
        return cls

    return _decorator


def register_memory(name: str) -> Callable[[T], T]:
    def _decorator(cls: T) -> T:
        MEMORY_REGISTRY.register(name, cls)
        return cls

    return _decorator
