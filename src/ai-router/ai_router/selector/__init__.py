"""Selector plugins — thuật toán chọn (key,model) cắm-rút được (PLAN §5.8).

Đổi thuật toán = đổi `selector.impl` trong routing.yaml, KHÔNG sửa code khác.
"""
from __future__ import annotations

from .banded_rotation import BandedRotation
from .base import ResolveRequest, Selector
from .elastic_banded import ElasticBanded
from .sticky_rotation import StickyRotationSoft
from .weighted_banded import WeightedBanded

# MOSA: thêm strategy = thêm 1 dòng ở đây + 1 file selector tự-register.
_REGISTRY: dict[str, type[Selector]] = {
    "banded_rotation": BandedRotation,          # ❖ DEFAULT toàn hệ (250K + save mode)
    "weighted_banded": WeightedBanded,          # node think: blend gpt + deepseek
    "sticky_rotation_soft": StickyRotationSoft,  # giữ làm lựa chọn thay thế
    "elastic_banded": ElasticBanded,            # co giãn theo tải + rải đều/swap toàn pool
}


def build_selector(impl: str, **kwargs) -> Selector:
    cls = _REGISTRY.get(impl)
    if cls is None:
        raise ValueError(f"selector impl không tồn tại: {impl}. Có: {list(_REGISTRY)}")
    return cls(**kwargs)


__all__ = ["Selector", "ResolveRequest", "build_selector"]
