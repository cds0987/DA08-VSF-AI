"""
Tests for production config hardening (config.py:84-97).

These tests verify that bad configurations raise errors at startup,
preventing insecure deployments from ever accepting traffic.
"""

import os
import pytest
from pydantic import ValidationError


def _make_settings(**overrides):
    """Create a fresh Settings instance without reading the .env file."""
    from pydantic_settings import BaseSettings
    from app.infrastructure.config import Settings

    # Build env dict: start from safe defaults, apply overrides
    safe_defaults = {
        "APP_ENV": "development",
        "AUTH_MODE": "mock",
        "MCP_MODE": "mock",
        "NATS_MODE": "mock",
        "LLM_MODE": "mock",
        "RATE_LIMITER_MODE": "memory",
        "JWT_SECRET_KEY": "your-secret-key-change-in-production",
        "ENABLE_DEV_ENDPOINTS": "false",
    }
    safe_defaults.update({k.upper(): str(v) for k, v in overrides.items()})

    # Temporarily patch env
    old_env = {k: os.environ.get(k) for k in safe_defaults}
    for k, v in safe_defaults.items():
        os.environ[k] = v
    try:
        return Settings()
    finally:
        for k, old in old_env.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


# ---------------------------------------------------------------------------
# Development mode — everything is allowed
# ---------------------------------------------------------------------------

def test_development_allows_mock_modes():
    s = _make_settings(app_env="development", auth_mode="mock", mcp_mode="mock")
    assert s.app_env == "development"


# ---------------------------------------------------------------------------
# Production mode — mock modes must be rejected
# ---------------------------------------------------------------------------

def test_production_rejects_mock_auth():
    with pytest.raises((ValueError, ValidationError)):
        _make_settings(
            app_env="production",
            auth_mode="mock",
            mcp_mode="real",
            nats_mode="nats",
            llm_mode="openai",
            rate_limiter_mode="redis",
            enable_dev_endpoints="false",
            jwt_secret_key="a" * 40,
        )


def test_production_rejects_mock_mcp():
    with pytest.raises((ValueError, ValidationError)):
        _make_settings(
            app_env="production",
            auth_mode="jwt",
            mcp_mode="mock",
            nats_mode="nats",
            llm_mode="openai",
            rate_limiter_mode="redis",
            enable_dev_endpoints="false",
            jwt_secret_key="a" * 40,
        )


def test_production_rejects_mock_nats():
    with pytest.raises((ValueError, ValidationError)):
        _make_settings(
            app_env="production",
            auth_mode="jwt",
            mcp_mode="real",
            nats_mode="mock",
            llm_mode="openai",
            rate_limiter_mode="redis",
            enable_dev_endpoints="false",
            jwt_secret_key="a" * 40,
        )


def test_production_rejects_mock_llm():
    with pytest.raises((ValueError, ValidationError)):
        _make_settings(
            app_env="production",
            auth_mode="jwt",
            mcp_mode="real",
            nats_mode="nats",
            llm_mode="mock",
            rate_limiter_mode="redis",
            enable_dev_endpoints="false",
            jwt_secret_key="a" * 40,
        )


def test_production_rejects_memory_rate_limiter():
    with pytest.raises((ValueError, ValidationError)):
        _make_settings(
            app_env="production",
            auth_mode="jwt",
            mcp_mode="real",
            nats_mode="nats",
            llm_mode="openai",
            rate_limiter_mode="memory",
            enable_dev_endpoints="false",
            jwt_secret_key="a" * 40,
        )


def test_production_rejects_dev_endpoints_enabled():
    with pytest.raises((ValueError, ValidationError)):
        _make_settings(
            app_env="production",
            auth_mode="jwt",
            mcp_mode="real",
            nats_mode="nats",
            llm_mode="openai",
            rate_limiter_mode="redis",
            enable_dev_endpoints="true",
            jwt_secret_key="a" * 40,
        )


# ---------------------------------------------------------------------------
# JWT secret hardening
# ---------------------------------------------------------------------------

def test_jwt_mode_requires_strong_secret():
    with pytest.raises((ValueError, ValidationError)):
        _make_settings(
            app_env="development",
            auth_mode="jwt",
            jwt_secret_key="your-secret-key-change-in-production",
        )


def test_jwt_mode_requires_min_32_chars():
    with pytest.raises((ValueError, ValidationError)):
        _make_settings(
            app_env="development",
            auth_mode="jwt",
            jwt_secret_key="short",
        )


def test_jwt_mode_accepts_strong_secret():
    s = _make_settings(
        app_env="development",
        auth_mode="jwt",
        jwt_secret_key="a-very-long-secret-key-that-is-strong-enough-for-jwt",
    )
    assert s.auth_mode == "jwt"


def test_mock_mode_allows_weak_jwt_secret():
    """In mock mode the JWT secret is irrelevant — no validation should fail."""
    s = _make_settings(auth_mode="mock", jwt_secret_key="weak")
    assert s.auth_mode == "mock"
