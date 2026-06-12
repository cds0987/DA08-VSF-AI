from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


@dataclass(frozen=True)
class HrSettings:
    host: str
    port: int
    log_level: str
    database_url: str
    internal_token: str
    auto_provision_leave_balance: bool
    nats_url: str
    nats_jetstream_enabled: bool
    user_events_enabled: bool


def load_settings(path: str | os.PathLike[str] | None = None) -> HrSettings:
    config_path = Path(path) if path else DEFAULT_CONFIG
    raw = _resolve(yaml.safe_load(config_path.read_text(encoding="utf-8")) or {})
    return HrSettings(
        host=str(raw.get("host") or "0.0.0.0").strip() or "0.0.0.0",
        port=int(str(raw.get("port") or 8004).strip() or 8004),
        log_level=str(raw.get("log_level") or "INFO").strip() or "INFO",
        database_url=str(raw.get("database_url") or "").strip(),
        internal_token=str(raw.get("internal_token") or "").strip(),
        auto_provision_leave_balance=_as_bool(raw.get("auto_provision_leave_balance"), True),
        nats_url=str(raw.get("nats_url") or "nats://nats:4222").strip() or "nats://nats:4222",
        nats_jetstream_enabled=_as_bool(raw.get("nats_jetstream_enabled"), True),
        user_events_enabled=_as_bool(raw.get("user_events_enabled"), True),
    )


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def get_settings() -> HrSettings:
    return load_settings()
