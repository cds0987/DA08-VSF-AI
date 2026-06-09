"""Tests for authentication / authorization middleware."""

import pytest
from httpx import AsyncClient

from tests.conftest import HR_TOKEN, FINANCE_TOKEN, ADMIN_TOKEN, auth


@pytest.mark.asyncio
async def test_no_token_returns_401(client: AsyncClient):
    r = await client.get("/conversations")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_invalid_token_returns_401(client: AsyncClient):
    r = await client.get("/conversations", headers=auth("not-a-valid-token"))
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_malformed_auth_header_returns_401(client: AsyncClient):
    r = await client.get("/conversations", headers={"Authorization": "Basic abc123"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_hr_token_authenticated(client: AsyncClient):
    r = await client.get("/conversations", headers=auth(HR_TOKEN))
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_finance_token_authenticated(client: AsyncClient):
    r = await client.get("/conversations", headers=auth(FINANCE_TOKEN))
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_admin_token_authenticated(client: AsyncClient):
    r = await client.get("/conversations", headers=auth(ADMIN_TOKEN))
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_non_admin_cannot_access_admin_metrics(hr_client: AsyncClient):
    r = await hr_client.get("/admin/metrics")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_access_admin_metrics(admin_client: AsyncClient):
    r = await admin_client.get("/admin/metrics")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_query_user_id_mismatch_returns_403(hr_client: AsyncClient):
    """user_id in body must match the authenticated token."""
    r = await hr_client.post("/query", json={
        "question": "Chính sách nghỉ phép?",
        "user_id": "00000000-0000-0000-0000-000000000000",  # wrong id
    })
    assert r.status_code == 403
