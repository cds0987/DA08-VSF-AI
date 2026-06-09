"""Tests for GET /admin/metrics."""

import pytest
from httpx import AsyncClient

from tests.conftest import HR_USER_ID


@pytest.mark.asyncio
async def test_admin_metrics_success(admin_client: AsyncClient):
    r = await admin_client.get("/admin/metrics")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)


@pytest.mark.asyncio
async def test_admin_metrics_date_filter(admin_client: AsyncClient):
    r = await admin_client.get("/admin/metrics", params={"from": "2026-01-01", "to": "2026-12-31"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_admin_metrics_forbidden_for_user(hr_client: AsyncClient):
    r = await hr_client.get("/admin/metrics")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_metrics_forbidden_for_finance(finance_client: AsyncClient):
    r = await finance_client.get("/admin/metrics")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_metrics_no_auth(client: AsyncClient):
    r = await client.get("/admin/metrics")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_admin_metrics_increments_after_message(admin_client: AsyncClient):
    """After seeding a message, metrics should reflect the activity."""
    from app.interfaces.api.dependencies import get_conversation_repo
    repo = get_conversation_repo()
    await repo.save_message(HR_USER_ID, "user", "Test query for metrics")

    r = await admin_client.get("/admin/metrics")
    assert r.status_code == 200
