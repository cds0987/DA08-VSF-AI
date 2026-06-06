import pytest

from app.infrastructure.config import Settings


def test_production_rejects_mock_modes():
    with pytest.raises(ValueError, match="production"):
        Settings(
            _env_file=None,
            app_env="production",
            auth_mode="mock",
            mcp_mode="real",
            nats_mode="nats",
            llm_mode="openai",
            openai_api_key="test-key",
            enable_dev_endpoints=False,
        )


def test_production_rejects_enabled_dev_endpoints():
    with pytest.raises(ValueError, match="ENABLE_DEV_ENDPOINTS"):
        Settings(
            _env_file=None,
            app_env="production",
            auth_mode="user_service",
            mcp_mode="real",
            nats_mode="nats",
            llm_mode="openai",
            openai_api_key="test-key",
            enable_dev_endpoints=True,
        )


def test_jwt_auth_rejects_weak_secret():
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(
            _env_file=None,
            auth_mode="jwt",
            jwt_secret_key="your-secret-key-change-in-production",
        )


def test_dev_endpoints_default_to_disabled(monkeypatch):
    monkeypatch.delenv("ENABLE_DEV_ENDPOINTS", raising=False)
    settings = Settings(_env_file=None)

    assert settings.enable_dev_endpoints is False
