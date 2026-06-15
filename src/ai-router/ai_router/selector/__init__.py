"""Selector plugins — thuật toán chọn (key,model) cắm-rút được (PLAN §5.8).

Đổi thuật toán = đổi `selector.impl` trong routing.yaml, KHÔNG sửa code khác.
"""
from __future__ import annotations

from .base import ResolveRequest, Selector
from .sticky_rotation import StickyRotationSoft

_REGISTRY: dict[str, type[Selector]] = {
    "sticky_rotation_soft": StickyRotationSoft,
}


def build_selector(impl: str, **kwargs) -> Selector:
    cls = _REGISTRY.get(impl)
    if cls is None:
        raise ValueError(f"selector impl không tồn tại: {impl}. Có: {list(_REGISTRY)}")
    return cls(**kwargs)


__all__ = ["Selector", "ResolveRequest", "build_selector"]
