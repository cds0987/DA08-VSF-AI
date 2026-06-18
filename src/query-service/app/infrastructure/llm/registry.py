"""Registry adapter MOSA — @register("name") + get_adapter("name").

Thêm 1 họ model mới = viết class NodeLLMAdapter + @register("ten") trong adapters/,
KHÔNG sửa loader/graph. profiles.yaml chỉ tham chiếu tên đã đăng ký.
"""
from __future__ import annotations

from .base import NodeLLMAdapter

_REGISTRY: dict[str, type[NodeLLMAdapter]] = {}


def register(name: str):
    """Decorator đăng ký 1 adapter dưới `name` (tên dùng trong profiles.yaml)."""

    def _decorator(cls: type[NodeLLMAdapter]) -> type[NodeLLMAdapter]:
        key = name.strip().lower()
        if not key:
            raise ValueError("adapter name rỗng")
        if key in _REGISTRY and _REGISTRY[key] is not cls:
            raise ValueError(f"adapter '{key}' đã được đăng ký bởi {_REGISTRY[key].__name__}")
        cls.name = key
        _REGISTRY[key] = cls
        return cls

    return _decorator


def get_adapter(name: str) -> NodeLLMAdapter:
    """Trả INSTANCE adapter theo tên. KeyError nếu chưa đăng ký."""
    key = (name or "").strip().lower()
    cls = _REGISTRY.get(key)
    if cls is None:
        raise KeyError(
            f"LLM adapter '{name}' chưa đăng ký. Có sẵn: {sorted(_REGISTRY)}"
        )
    return cls()


def is_registered(name: str) -> bool:
    return (name or "").strip().lower() in _REGISTRY


def available() -> list[str]:
    return sorted(_REGISTRY)
