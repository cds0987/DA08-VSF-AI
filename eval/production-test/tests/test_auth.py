from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.auth import AuthSession
from lib.config import Settings, validate_settings


def settings() -> Settings:
    return Settings(
        prod_base_url="https://prod.example",
        prod_api_base_url="https://prod.example",
        prod_email="user@example.com",
        prod_password="pw",
        prod_access_token=None,
        prod_refresh_token=None,
        user_service_path="/api/user",
        query_service_path="/api/query",
        document_service_path="/api/documents",
        mcp_url=None,
        mcp_internal_token=None,
        gateway_basic_auth=None,
        dataset_root=Path("eval/dataset"),
        dataset="dataset_new",
        output_root=Path("out"),
        question_timeout_seconds=30,
        concurrency=1,
        limit=1,
        question_offset=0,
        dry_run=False,
    )


@pytest.mark.asyncio
async def test_login_and_me_extract_user() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"access_token": "access", "refresh_token": "refresh", "token_type": "bearer"})
        if request.url.path.endswith("/auth/me"):
            assert request.headers["Authorization"] == "Bearer access"
            return httpx.Response(200, json={"id": "u1", "email": "user@example.com", "role": "user", "account_type": "internal", "department": "HR"})
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        auth = AuthSession(settings(), client)
        await auth.login()

    assert auth.user_id == "u1"
    assert auth.public_auth_info()["user"]["email"] == "user@example.com"


@pytest.mark.asyncio
async def test_refresh_falls_back_to_relogin() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"access_token": "access", "refresh_token": "refresh"})
        if request.url.path.endswith("/auth/me"):
            return httpx.Response(200, json={"id": "u1", "email": "user@example.com", "role": "user", "account_type": "internal", "department": "HR"})
        if request.url.path.endswith("/auth/refresh"):
            return httpx.Response(401, json={"detail": "expired"})
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        auth = AuthSession(settings(), client)
        await auth.login()
        await auth.recover()

    assert auth.stats.relogin_count == 1
    assert any(path.endswith("/auth/refresh") for path in calls)


def test_validate_settings_rejects_placeholder_base_url() -> None:
    cfg = Settings(
        prod_base_url="https://your-production-host.example.com",
        prod_api_base_url="https://your-production-host.example.com",
        prod_email="user@example.com",
        prod_password="pw",
        prod_access_token=None,
        prod_refresh_token=None,
        user_service_path="/api/user",
        query_service_path="/api/query",
        document_service_path="/api/documents",
        mcp_url=None,
        mcp_internal_token=None,
        gateway_basic_auth=None,
        dataset_root=Path("eval/dataset"),
        dataset="dataset_new",
        output_root=Path("out"),
        question_timeout_seconds=30,
        concurrency=1,
        limit=1,
        question_offset=0,
        dry_run=False,
    )
    with pytest.raises(SystemExit, match="placeholder"):
        validate_settings(cfg)


@pytest.mark.asyncio
async def test_bootstrap_from_access_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/me"):
            assert request.headers["Authorization"] == "Bearer token-1"
            return httpx.Response(200, json={"id": "u1", "email": "user@example.com", "role": "user", "account_type": "internal", "department": "HR"})
        return httpx.Response(404)

    cfg = Settings(
        prod_base_url="https://prod.example",
        prod_api_base_url="https://prod.example",
        prod_email="user@example.com",
        prod_password="pw",
        prod_access_token="token-1",
        prod_refresh_token=None,
        user_service_path="/api/user",
        query_service_path="/api/query",
        document_service_path="/api/documents",
        mcp_url=None,
        mcp_internal_token=None,
        gateway_basic_auth=None,
        dataset_root=Path("eval/dataset"),
        dataset="dataset_new",
        output_root=Path("out"),
        question_timeout_seconds=30,
        concurrency=1,
        limit=1,
        question_offset=0,
        dry_run=False,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        auth = AuthSession(cfg, client)
        await auth.login()
    assert auth.user_id == "u1"
