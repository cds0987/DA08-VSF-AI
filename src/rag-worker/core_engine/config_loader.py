from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from core_engine.config_schema import PipelineConfig

_ENV_PATTERN = re.compile(r"^\$\{([A-Z0-9_]+)(?::-(.*))?\}$")


def _interpolate_value(value: Any) -> Any:
    # Whole-value only: `${VAR}` được expand khi nó là TOÀN BỘ scalar (anchored).
    # `${VAR}` lồng trong chuỗi lớn hơn (vd "http://${HOST}:6333") KHÔNG được expand —
    # trả về literal, không làm hỏng giá trị. Cần inline thì set sẵn giá trị đầy đủ qua env.
    if isinstance(value, dict):
        return {key: _interpolate_value(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_interpolate_value(item) for item in value]
    if not isinstance(value, str):
        return value
    match = _ENV_PATTERN.match(value.strip())
    if not match:
        return value
    name, default = match.groups()
    raw = os.getenv(name)
    if raw is None or raw == "":
        if default is None:
            raise ValueError(f"Missing required environment variable: {name}")
        return default
    return raw


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _resolve_profile(
    name: str,
    profiles: dict[str, Any],
    seen: set[str] | None = None,
) -> dict[str, Any]:
    seen = seen or set()
    if name in seen:
        raise ValueError(f"Cyclic profile extends detected at {name!r}")
    if name not in profiles:
        raise ValueError(f"Unknown pipeline profile: {name}")
    seen.add(name)
    raw = dict(profiles[name] or {})
    extends = raw.pop("extends", None)
    if not extends:
        return raw
    return _deep_merge(_resolve_profile(str(extends), profiles, seen), raw)


def _reject_nested_embed_keys(cfg: dict[str, Any]) -> None:
    def walk(node: Any, *, path: tuple[str, ...]) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "embed":
                    raise ValueError(
                        "Embed config must live in top-level embedder block: "
                        + ".".join(path + (str(key),))
                    )
                if key == "embedder" and path:
                    raise ValueError(
                        "Embed config must live in top-level embedder block: "
                        + ".".join(path + (str(key),))
                    )
                walk(value, path=path + (str(key),))
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, path=path + (str(index),))

    walk(cfg, path=())


def load_config(path: str | os.PathLike[str]) -> PipelineConfig:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    profiles = payload.get("profiles")
    if profiles:
        # Interpolate `active` riêng để chọn profile; KHÔNG interpolate cả payload ở đây —
        # nếu không, một `${VAR}` bắt buộc ở profile KHÔNG active vẫn làm vỡ việc load.
        active_raw = payload.get("active")
        active = os.getenv("PIPELINE_PROFILE") or (
            _interpolate_value(active_raw) if active_raw is not None else None
        )
        if not active:
            raise ValueError("Pipeline config must declare active profile or PIPELINE_PROFILE")
        resolved = _resolve_profile(str(active), profiles)
    else:
        resolved = payload
    # Chỉ interpolate profile đã chọn + đã merge `extends`.
    resolved = _interpolate_value(resolved)
    _reject_nested_embed_keys(resolved)
    return PipelineConfig.model_validate(resolved)
