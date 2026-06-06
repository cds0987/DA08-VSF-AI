import pytest

from app.infrastructure.cache.rate_limiter import InMemoryRateLimiter, RedisRateLimiter
from app.infrastructure.config import get_settings
from app.interfaces.api.dependencies import get_rate_limiter


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.expirations: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key: str, ttl: int) -> None:
        self.expirations[key] = ttl


class FakeRedisModule:
    def __init__(self) -> None:
        self.client = FakeRedis()

    def from_url(self, url: str, *, encoding: str, decode_responses: bool):
        return self.client


@pytest.mark.asyncio
async def test_inmemory_rate_limiter_is_async_for_router_use():
    limiter = InMemoryRateLimiter(max_requests_per_minute=1)

    assert await limiter.allow("user-1") is True
    assert await limiter.allow("user-1") is False


@pytest.mark.asyncio
async def test_redis_rate_limiter_shares_counts_across_instances():
    redis_module = FakeRedisModule()
    first = RedisRateLimiter("redis://test", max_requests_per_minute=1, redis_module=redis_module)
    second = RedisRateLimiter("redis://test", max_requests_per_minute=1, redis_module=redis_module)

    assert await first.allow("user-1") is True
    assert await second.allow("user-1") is False


def test_production_dependency_uses_redis_rate_limiter(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "user_service")
    monkeypatch.setenv("MCP_MODE", "real")
    monkeypatch.setenv("NATS_MODE", "nats")
    monkeypatch.setenv("LLM_MODE", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("RATE_LIMITER_MODE", "redis")
    monkeypatch.setenv("ENABLE_DEV_ENDPOINTS", "false")
    get_settings.cache_clear()
    get_rate_limiter.cache_clear()

    assert isinstance(get_rate_limiter(), RedisRateLimiter)
