"""Composable Qdrant remote-client kwargs builders."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from core_engine.registry import Registry
from core_engine.vectorstore.config import (
    DEFAULT_REMOTE_TIMEOUT,
    VectorStoreConfig,
    basic_auth_header,
    normalize_remote_qdrant_url,
)

ClientKwargsContributor = Callable[[VectorStoreConfig, dict[str, Any]], None]

_CONTRIBUTORS: Registry[ClientKwargsContributor] = Registry(
    "qdrant_connection", entry_point_group="rag_worker.qdrant_connection"
)


def register_connection_option(
    name: str,
    contributor: ClientKwargsContributor,
    *,
    override: bool = False,
) -> None:
    _CONTRIBUTORS.register(name, contributor, override=override)


def available_connection_options() -> list[str]:
    return _CONTRIBUTORS.available()


def build_remote_client_kwargs(config: VectorStoreConfig) -> dict[str, Any]:
    kwargs: dict[str, Any] = dict(config.options)
    for name in _CONTRIBUTORS.available():
        _CONTRIBUTORS.get(name)(config, kwargs)
    return kwargs


def _contribute_url(config: VectorStoreConfig, kwargs: dict[str, Any]) -> None:
    kwargs["url"] = normalize_remote_qdrant_url(config.url) or None


def _contribute_api_key(config: VectorStoreConfig, kwargs: dict[str, Any]) -> None:
    kwargs["api_key"] = config.api_key or None


def _contribute_timeout(config: VectorStoreConfig, kwargs: dict[str, Any]) -> None:
    del config
    kwargs.setdefault("timeout", int(os.getenv("QDRANT_TIMEOUT", str(DEFAULT_REMOTE_TIMEOUT))))


def _contribute_basic_auth(config: VectorStoreConfig, kwargs: dict[str, Any]) -> None:
    header = basic_auth_header(config.basic_auth)
    if header:
        headers = dict(kwargs.get("headers") or {})
        headers.setdefault("Authorization", header)
        kwargs["headers"] = headers


register_connection_option("url", _contribute_url)
register_connection_option("api_key", _contribute_api_key)
register_connection_option("timeout", _contribute_timeout)
register_connection_option("basic_auth", _contribute_basic_auth)
