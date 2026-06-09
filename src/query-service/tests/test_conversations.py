"""Tests for GET /conversations and DELETE /conversations."""

import pytest
from httpx import AsyncClient

from tests.conftest import HR_USER_ID, FINANCE_USER_ID


@pytest.mark.asyncio
async def test_get_conversations_empty(hr_client: AsyncClient):
    r = await hr_client.get("/conversations")
    assert r.status_code == 200
    body = r.json()
    assert "messages" in body
    assert body["messages"] == []


@pytest.mark.asyncio
async def test_get_conversations_pagination_defaults(hr_client: AsyncClient):
    r = await hr_client.get("/conversations")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_get_conversations_custom_pagination(hr_client: AsyncClient):
    r = await hr_client.get("/conversations", params={"limit": 5, "offset": 0})
    assert r.status_code == 200
    assert "messages" in r.json()


@pytest.mark.asyncio
async def test_clear_conversations_returns_message(hr_client: AsyncClient):
    r = await hr_client.delete("/conversations")
    assert r.status_code == 200
    assert "message" in r.json()


@pytest.mark.asyncio
async def test_conversations_isolated_per_user(hr_client: AsyncClient, finance_client: AsyncClient):
    """Each user sees only their own conversation history."""
    # Save a message for HR user via direct repo
    from app.interfaces.api.dependencies import get_conversation_repo
    repo = get_conversation_repo()
    await repo.save_message(HR_USER_ID, "user", "HR test message")

    hr_resp = await hr_client.get("/conversations")
    finance_resp = await finance_client.get("/conversations")

    hr_messages = hr_resp.json()["messages"]
    finance_messages = finance_resp.json()["messages"]

    assert any("HR test message" in m["content"] for m in hr_messages)
    assert not any("HR test message" in m["content"] for m in finance_messages)


@pytest.mark.asyncio
async def test_clear_only_affects_own_history(hr_client: AsyncClient, finance_client: AsyncClient):
    """DELETE /conversations must only clear the calling user's history."""
    from app.interfaces.api.dependencies import get_conversation_repo
    repo = get_conversation_repo()
    await repo.save_message(FINANCE_USER_ID, "user", "Finance message")

    await hr_client.delete("/conversations")

    finance_resp = await finance_client.get("/conversations")
    assert any("Finance message" in m["content"] for m in finance_resp.json()["messages"])
