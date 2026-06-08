"""Composable Qdrant remote-client kwargs builders for mcp-service."""

from __future__ import annotations

import base64
import os
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlparse, urlunparse

from app.core.config import McpSettings

DEFAULT_REMOTE_TIMEOUT = 30
SCHEME_FORCED_PORT: Mapping[str, int] = {"https": 443}
ClientKwargsContributor = Callable[[McpSettings, dict[str, Any]], None]
_CONTRIBUTORS: dict[str, ClientKwargsContributor] = {}


def register_connection_option(
    name: str,
    contributor: ClientKwargsContributor,
    *,
    override: bool = False,
) -> None:
    key = name.lower()
    if key in _CONTRIBUTORS and not override:
        raise ValueError(f"qdrant_connection:{name!r} da dang ky")
    _CONTRIBUTORS[key] = contributor


def available_connection_options() -> list[str]:
    return sorted(_CONTRIBUTORS)


def basic_auth_header(creds: str) -> str:
    creds = (creds or "").strip()
    if not creds or ":" not in creds:
        return ""
    return "Basic " + base64.b64encode(creds.encode()).decode()


def normalize_remote_url(url: str) -> str:
    if not url:
        return url
    parsed = urlparse(url)
    if not parsed.scheme or parsed.port is not None or not parsed.hostname:
        return url
    port = SCHEME_FORCED_PORT.get(parsed.scheme)
    if port is None:
        return url
    return urlunparse(parsed._replace(netloc=f"{parsed.hostname}:{port}"))


def build_remote_client_kwargs(settings: McpSettings) -> dict[str, Any]:
    kwargs: dict[str, Any] = dict(settings.options)
    for name in available_connection_options():
        _CONTRIBUTORS[name](settings, kwargs)
    return kwargs


def _contribute_url(settings: McpSettings, kwargs: dict[str, Any]) -> None:
    kwargs["url"] = normalize_remote_url(settings.url) or None


def _contribute_api_key(settings: McpSettings, kwargs: dict[str, Any]) -> None:
    kwargs["api_key"] = settings.api_key or None


def _contribute_timeout(settings: McpSettings, kwargs: dict[str, Any]) -> None:
    # Ưu tiên: options["timeout"] > config.yaml params.timeout > env QDRANT_TIMEOUT > default.
    if "timeout" in kwargs:
        return
    if settings.timeout is not None:
        kwargs["timeout"] = settings.timeout
        return
    kwargs["timeout"] = int(os.getenv("QDRANT_TIMEOUT", str(DEFAULT_REMOTE_TIMEOUT)))


def _contribute_basic_auth(settings: McpSettings, kwargs: dict[str, Any]) -> None:
    header = basic_auth_header(settings.basic_auth)
    if header:
        headers = dict(kwargs.get("headers") or {})
        headers.setdefault("Authorization", header)
        kwargs["headers"] = headers


register_connection_option("url", _contribute_url)
register_connection_option("api_key", _contribute_api_key)
register_connection_option("timeout", _contribute_timeout)
register_connection_option("basic_auth", _contribute_basic_auth)
