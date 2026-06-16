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
async def test_per_ip_limit_blocks_across_users(hr_client: AsyncClient):
    """Trần per-IP chặn dù mỗi user còn quota riêng: 1 IP gửi quá nhiều -> 429."""
    from app.interfaces.api.dependencies import get_rate_limiter

    limiter = get_rate_limiter()
    ip = "203.0.113.7"
    # Bơm tới sát trần per-IP bằng nhiều user khác nhau (mỗi user chưa chạm trần user).
    for i in range(60):
        assert await limiter.allow(f"user-{i}", ip) is True
    # Cùng IP, user mới hoàn toàn -> vẫn bị chặn vì trần IP đã đầy.
    assert await limiter.allow("brand-new-user", ip) is False


@pytest.mark.asyncio
async def test_global_limit_blocks_all(hr_client: AsyncClient):
    """Trần tổng toàn service: đủ request từ nhiều IP/user khác nhau -> chặn."""
    from app.interfaces.api.dependencies import get_rate_limiter

    limiter = get_rate_limiter()
    # Mỗi (user, ip) duy nhất để KHÔNG chạm trần user/ip, chỉ dồn vào trần global=600.
    for i in range(600):
        assert await limiter.allow(f"u{i}", f"10.0.{i // 256}.{i % 256}") is True
    assert await limiter.allow("u-final", "10.9.9.9") is False


@pytest.mark.asyncio
async def test_concurrency_cap_per_user():
    """Quá nhiều stream song song / user -> acquire trả None; release mở lại slot."""
    from app.interfaces.api.dependencies import get_rate_limiter

    limiter = get_rate_limiter()
    tokens = []
    for _ in range(3):  # query_max_concurrent_per_user mặc định = 3
        t = await limiter.acquire(HR_USER_ID)
        assert t is not None
        tokens.append(t)
    # Slot thứ 4 bị từ chối.
    assert await limiter.acquire(HR_USER_ID) is None
    # Trả 1 slot -> acquire lại được.
    await limiter.release(HR_USER_ID, tokens[0])
    assert await limiter.acquire(HR_USER_ID) is not None


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
