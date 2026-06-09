"""Tests for GET /health."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_ok(client: AsyncClient):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["auth"] == "mock"
    assert body["mcp_service"] == "mock"
    assert body["database"] == "mock"
    assert body["degraded_reasons"] == []


@pytest.mark.asyncio
async def test_health_no_auth_required(client: AsyncClient):
    """Health endpoint must be reachable without any token."""
    r = await client.get("/health")
    assert r.status_code != 401


@pytest.mark.asyncio
async def test_health_schema_fields(client: AsyncClient):
    """All expected fields must be present in the response."""
    r = await client.get("/health")
    body = r.json()
    for field in ("status", "database", "redis", "mcp_service", "nats", "auth", "llm", "degraded_reasons"):
        assert field in body, f"Missing field: {field}"
