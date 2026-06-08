from __future__ import annotations

import pytest

from core_engine.vectorstore import connection as connection_module
from core_engine.vectorstore.config import VectorStoreConfig, basic_auth_header
from core_engine.vectorstore.connection import (
    available_connection_options,
    build_remote_client_kwargs,
    register_connection_option,
)


def test_available_connection_options_includes_builtin_contributors() -> None:
    assert available_connection_options() == ["api_key", "basic_auth", "timeout", "url"]


def test_build_remote_client_kwargs_matches_existing_remote_behavior() -> None:
    cfg = VectorStoreConfig(
        url="https://qdrant.example.run.app",
        api_key="secret",
        basic_auth="user:pass",
        options={"timeout": 12, "headers": {"X-Trace": "1"}},
    )

    kwargs = build_remote_client_kwargs(cfg)

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
    cfg = VectorStoreConfig(
        url="http://qdrant:6333",
        basic_auth="user:pass",
        options={"headers": {"Authorization": "Bearer keep-me"}},
    )

    kwargs = build_remote_client_kwargs(cfg)

    assert kwargs["headers"]["Authorization"] == "Bearer keep-me"


def test_explicit_fields_override_same_keys_in_options() -> None:
    cfg = VectorStoreConfig(
        url="https://field.example",
        api_key="field-key",
        options={"url": "https://option.example", "api_key": "option-key"},
    )

    kwargs = build_remote_client_kwargs(cfg)

    assert kwargs["url"] == "https://field.example:443"
    assert kwargs["api_key"] == "field-key"


def test_register_connection_option_can_extend_without_editing_builder(monkeypatch) -> None:
    name = "zz_test_marker"
    monkeypatch.setattr(
        connection_module._CONTRIBUTORS,
        "_factories",
        dict(connection_module._CONTRIBUTORS._factories),
    )

    def contribute_marker(config: VectorStoreConfig, kwargs: dict[str, object]) -> None:
        del config
        kwargs["marker"] = "ok"

    register_connection_option(name, contribute_marker, override=True)
    kwargs = build_remote_client_kwargs(VectorStoreConfig(url="http://qdrant:6333"))

    assert kwargs["marker"] == "ok"


def test_duplicate_connection_option_requires_override() -> None:
    with pytest.raises(ValueError):
        register_connection_option("url", lambda config, kwargs: None)


def test_config_timeout_used_when_set() -> None:
    cfg = VectorStoreConfig(url="http://qdrant:6333", timeout=45)
    assert build_remote_client_kwargs(cfg)["timeout"] == 45


def test_options_timeout_wins_over_config_timeout() -> None:
    cfg = VectorStoreConfig(url="http://qdrant:6333", timeout=45, options={"timeout": 12})
    assert build_remote_client_kwargs(cfg)["timeout"] == 12


def test_env_timeout_used_when_config_timeout_unset(monkeypatch) -> None:
    monkeypatch.setenv("QDRANT_TIMEOUT", "77")
    cfg = VectorStoreConfig(url="http://qdrant:6333")  # timeout=None
    assert build_remote_client_kwargs(cfg)["timeout"] == 77
