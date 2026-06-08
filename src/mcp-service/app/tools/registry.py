"""Shared registry for pluggable MCP tools."""

from __future__ import annotations

import importlib.metadata
from typing import Generic, TypeVar

T = TypeVar("T")


class Registry(Generic[T]):
    def __init__(self, label: str, *, entry_point_group: str | None = None) -> None:
        self._label = label
        self._group = entry_point_group
        self._factories: dict[str, T] = {}
        self._entry_point_names: set[str] = set()
        self._entry_points_loaded = False

    def is_entry_point(self, name: str) -> bool:
        """True nếu `name` được nạp từ entry-point (tool bên thứ ba), không phải
        built-in `register()`. Dùng để policy enabled mặc định khác nhau."""
        self._ensure_entry_points()
        return name.lower() in self._entry_point_names

    def register(self, name: str, factory: T, *, override: bool = False) -> T:
        key = name.lower()
        if key in self._factories and not override:
            raise ValueError(
                f"{self._label}:{name!r} da dang ky. "
                "Truyen override=True neu co y thay the."
            )
        self._factories[key] = factory
        return factory

    def get(self, name: str) -> T:
        self._ensure_entry_points()
        factory = self._factories.get(name.lower())
        if factory is None:
            raise ValueError(
                f"{self._label}={name!r} chua dang ky. Co: {self.available()}"
            )
        return factory

    def available(self) -> list[str]:
        self._ensure_entry_points()
        return sorted(self._factories)

    def _ensure_entry_points(self) -> None:
        if self._entry_points_loaded or not self._group:
            return
        self._entry_points_loaded = True
        for entry_point in importlib.metadata.entry_points(group=self._group):
            if entry_point.name.lower() not in self._factories:
                self.register(entry_point.name, entry_point.load())
                self._entry_point_names.add(entry_point.name.lower())
