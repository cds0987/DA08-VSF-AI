from __future__ import annotations

import pytest

from app.core import connection as connection_module
from app.core.config import McpSettings
from app.core.connection import (
    available_connection_options,
    basic_auth_header,
    build_remote_client_kwargs,
    register_connection_option,
)


def _settings(**overrides) -> McpSettings:
    base = dict(
        host="0.0.0.0",
        port=8003,
        log_level="INFO",
        app_env="development",
        internal_token="",
        provider="qdrant",
        collection="rag_chatbot",
        embed_model="offline",
        dimension=256,
        url="",
        api_key="",
        embed_base_url="",
        embed_api_key="",
        rerank_impl="none",
        rerank_model="gpt-4o-mini",
        rerank_base_url="",
        rerank_api_key="",
        rerank_timeout_seconds=30.0,
        rerank_batch_size=8,
        rerank_passage_chars=800,
        top_k_candidates=20,
        rerank_top_k=3,
        rerank_threshold=0.0,
        basic_auth="",
        options={},
    )
    base.update(overrides)
    return McpSettings(**base)


def test_available_connection_options_includes_builtin_contributors() -> None:
    assert available_connection_options() == ["api_key", "basic_auth", "timeout", "url"]


def test_build_remote_client_kwargs_matches_existing_remote_behavior() -> None:
    settings = _settings(
        url="https://qdrant.example.run.app",
        api_key="secret",
        basic_auth="user:pass",
        options={"timeout": 12, "headers": {"X-Trace": "1"}},
    )

    kwargs = build_remote_client_kwargs(settings)

    assert kwargs == {
        "url": "https://qdrant.example.run.app:443",
        "api_key": "secret",
        "timeout": 12,
        "headers": {
            "X-Trace": "1",
            "Authorization": basic_auth_header("user:pass"),
        },
    }


def test_basic_auth_does_not_override_existing_authorization_header() -> None:
    settings = _settings(
        url="http://qdrant:6333",
        basic_auth="user:pass",
        options={"headers": {"Authorization": "Bearer keep-me"}},
    )

    kwargs = build_remote_client_kwargs(settings)

    assert kwargs["headers"]["Authorization"] == "Bearer keep-me"


def test_explicit_fields_override_same_keys_in_options() -> None:
    settings = _settings(
        url="https://field.example",
        api_key="field-key",
        options={"url": "https://option.example", "api_key": "option-key"},
    )

    kwargs = build_remote_client_kwargs(settings)

    assert kwargs["url"] == "https://field.example:443"
    assert kwargs["api_key"] == "field-key"


def test_register_connection_option_can_extend_without_editing_builder(monkeypatch) -> None:
    name = "zz_test_marker"
    monkeypatch.setattr(connection_module, "_CONTRIBUTORS", dict(connection_module._CONTRIBUTORS))

    def contribute_marker(settings: McpSettings, kwargs: dict[str, object]) -> None:
        del settings
        kwargs["marker"] = "ok"

    register_connection_option(name, contribute_marker, override=True)
    kwargs = build_remote_client_kwargs(_settings(url="http://qdrant:6333"))

    assert kwargs["marker"] == "ok"


def test_duplicate_connection_option_requires_override() -> None:
    with pytest.raises(ValueError):
        register_connection_option("url", lambda settings, kwargs: None)
