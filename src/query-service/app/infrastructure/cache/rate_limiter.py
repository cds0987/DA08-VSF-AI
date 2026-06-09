from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone


class RateLimiterUnavailable(RuntimeError):
    """Raised when the configured shared limiter cannot be reached."""


class InMemoryRateLimiter:
    def __init__(self, max_requests_per_minute: int) -> None:
        self._max = max_requests_per_minute
        self._hits: dict[str, deque[datetime]] = defaultdict(deque)

    async def allow(self, user_id: str) -> bool:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=60)
        hits = self._hits[user_id]
        while hits and hits[0] < cutoff:
            hits.popleft()
        if len(hits) >= self._max:
            return False
        hits.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()


class RedisRateLimiter:
    def __init__(
        self,
        redis_url: str,
        max_requests_per_minute: int,
        redis_module=None,
    ) -> None:
        self._redis_url = redis_url
        self._max = max_requests_per_minute
        self._redis_module = redis_module
        self._client = None

    async def allow(self, user_id: str) -> bool:
        now = datetime.now(timezone.utc)
        bucket = int(now.timestamp() // 60)
        key = f"query_rate_limit:{user_id}:{bucket}"
        try:
            client = self._get_client()
            count = await client.incr(key)
            if count == 1:
                await client.expire(key, 60)
        except Exception as exc:
            raise RateLimiterUnavailable("Redis rate limiter unavailable") from exc
        return int(count) <= self._max

    async def ping(self) -> None:
        """Raise if Redis is unreachable. Used by /health."""
        try:
            await self._get_client().ping()
        except Exception as exc:
            raise RateLimiterUnavailable("Redis ping failed") from exc

    def reset(self) -> None:
        self._client = None

    def _get_client(self):
        if self._client is None:
            redis_module = self._redis_module or _import_redis_asyncio()
            self._client = redis_module.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._client


def _import_redis_asyncio():
    try:
        import redis.asyncio as redis_asyncio
    except ImportError as exc:
        raise RuntimeError("redis>=5.0.0 is required for RATE_LIMITER_MODE=redis") from exc
    return redis_asyncio
