"""Tests for rate limiting on POST /query."""

import pytest
from httpx import AsyncClient

from tests.conftest import HR_USER_ID, FINANCE_USER_ID


@pytest.mark.asyncio
async def test_rate_limit_allows_first_request(hr_client: AsyncClient):
    r = await hr_client.post("/query", json={
        "question": "Chính sách nghỉ phép?",
        "user_id": HR_USER_ID,
    })
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_blocks_after_exceeding(hr_client: AsyncClient):
    """After exhausting the per-minute budget, the next request must return 429."""
    from app.interfaces.api.dependencies import get_rate_limiter

    limiter = get_rate_limiter()
    user_id = HR_USER_ID

    # Exhaust the budget directly via the limiter (faster than sending HTTP requests)
    for _ in range(20):
        await limiter.allow(user_id)

    r = await hr_client.post("/query", json={
        "question": "One more request",
        "user_id": user_id,
    })
    assert r.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_is_per_user(hr_client: AsyncClient, finance_client: AsyncClient):
    """Rate limit buckets must be isolated per user — exhausting HR should not block Finance."""
    from app.interfaces.api.dependencies import get_rate_limiter

    limiter = get_rate_limiter()
    for _ in range(20):
        await limiter.allow(HR_USER_ID)

    # HR is now rate-limited
    r_hr = await hr_client.post("/query", json={
        "question": "Another question",
        "user_id": HR_USER_ID,
    })
    assert r_hr.status_code == 429

    # Finance user must still be allowed
    r_finance = await finance_client.post("/query", json={
        "question": "Chính sách nghỉ phép?",
        "user_id": FINANCE_USER_ID,
    })
    assert r_finance.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_resets_after_window(hr_client: AsyncClient):
    """After reset, the user should be allowed again."""
    from app.interfaces.api.dependencies import get_rate_limiter

    limiter = get_rate_limiter()
    for _ in range(20):
        await limiter.allow(HR_USER_ID)

    # Force reset the limiter state
    limiter.reset()

    r = await hr_client.post("/query", json={
        "question": "Câu hỏi sau khi reset",
        "user_id": HR_USER_ID,
    })
    assert r.status_code == 200
