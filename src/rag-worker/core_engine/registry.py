"""Registry — MỘT cơ chế đăng ký dùng chung cho mọi component tháo-lắp in-process.

Trước đây có 3 registry rời (chunker/captioner/reranker · vector_store · parser),
mỗi cái tự cài lại phần bookkeeping (đăng ký · resolve · guard trùng tên ·
liệt kê). Primitive này tách bookkeeping đó ra MỘT chỗ; mỗi component vẫn giữ
chữ ký factory hợp với layer của nó (factory signature là tham số generic `T`),
nhưng dùng CHUNG `register` / `get` / `available` → contributor học một pattern.

Hai năng lực:
- `register(name, factory)` — guard trùng tên im lặng (phải `override=True` mới đè).
- `get(name)` / `available()` — resolve + liệt kê; báo `"chua dang ky"` kèm danh sách.

Discovery KHÔNG cần import side-effect: bên thứ ba khai báo entry-point trong
package metadata (`[project.entry-points."rag_worker.<component>"]`) thay vì phải
chắc module của họ được import đâu đó. Built-in vẫn `register(...)` tường minh lúc
import; entry-point được nạp LAZY ở lần `get`/`available` đầu tiên và **built-in
thắng khi trùng tên** (không đè built-in im lặng qua entry-point).
"""

from __future__ import annotations

import importlib.metadata
from typing import Generic, List, TypeVar

T = TypeVar("T")


class Registry(Generic[T]):
    def __init__(self, label: str, *, entry_point_group: str | None = None) -> None:
        self._label = label
        self._group = entry_point_group
        self._factories: dict[str, T] = {}
        self._entry_points_loaded = False

    def register(self, name: str, factory: T, *, override: bool = False) -> T:
        """Đăng ký factory cho `name`. Trùng tên mà ko `override=True` -> raise."""
        key = name.lower()
        if key in self._factories and not override:
            raise ValueError(
                f"{self._label}:{name!r} da dang ky. "
                "Truyen override=True neu co y thay the."
            )
        self._factories[key] = factory
        return factory

    def get(self, name: str) -> T:
        """Lấy factory theo tên; chưa đăng ký -> ValueError kèm danh sách có sẵn."""
        self._ensure_entry_points()
        factory = self._factories.get(name.lower())
        if factory is None:
            raise ValueError(
                f"{self._label}={name!r} chua dang ky. Co: {self.available()}"
            )
        return factory

    def available(self) -> List[str]:
        self._ensure_entry_points()
        return sorted(self._factories)

    def _ensure_entry_points(self) -> None:
        # Nạp một lần, lazy. Built-in đã register lúc import (trước get/available
        # đầu tiên) nên check `not in` cho built-in thắng khi trùng tên.
        if self._entry_points_loaded or not self._group:
            return
        self._entry_points_loaded = True
        for ep in importlib.metadata.entry_points(group=self._group):
            if ep.name.lower() not in self._factories:
                self.register(ep.name, ep.load())
