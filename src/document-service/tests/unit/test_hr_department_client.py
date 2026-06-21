"""Test HrDepartmentClient: parse {items:[{user_id,department}]} -> map, cache TTL, fail-safe."""
import httpx
import pytest

from app.infrastructure.external.hr_department_client import HrDepartmentClient


@pytest.mark.asyncio
async def test_parses_items_and_caches():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"items": [
            {"user_id": "u1", "department": "HR"},
            {"user_id": "u2", "department": "Finance"},
        ]})

    client = HrDepartmentClient("http://hr", ttl_seconds=999, transport=httpx.MockTransport(handler))
    assert await client.get_department("u1") == "HR"
    assert await client.get_department("u2") == "Finance"
    assert await client.get_department("ghost") == ""   # không có -> ""
    assert calls["n"] == 1                                # cache: chỉ fetch 1 lần


@pytest.mark.asyncio
async def test_hr_down_returns_empty_fail_closed():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("hr down")

    client = HrDepartmentClient("http://hr", transport=httpx.MockTransport(handler))
    assert await client.get_department("u1") == ""       # lỗi -> "" -> ACL fail-closed


@pytest.mark.asyncio
async def test_non_200_returns_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    client = HrDepartmentClient("http://hr", transport=httpx.MockTransport(handler))
    assert await client.get_department("u1") == ""
