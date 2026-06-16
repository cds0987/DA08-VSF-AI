"""Rate limiting for POST /query.

Bốn lớp bảo vệ chống spam / overload (tất cả đều SLIDING-WINDOW 60s, không phải
fixed-window — nên KHÔNG cho burst gấp đôi ở ranh giới phút):

  1. per-user   — mỗi user tối đa N request/phút.
  2. per-ip     — mỗi IP tối đa M request/phút (chặn 1 IP nhiều tài khoản).
  3. global     — toàn service tối đa G request/phút (trần tổng bảo vệ hạ tầng).
  4. concurrency— mỗi user tối đa C request ĐANG chạy song song (SSE/LLM stream
                  dài) — đây mới là thứ chặn đốt token LLM thật sự.

`allow(user_id, ip)` kiểm tra (1)(2)(3) atomically. `acquire(user_id)` /
`release(user_id, token)` quản (4) quanh vòng đời stream.
"""

from collections import defaultdict, deque
from datetime import datetime, timezone
from uuid import uuid4

_WINDOW_SECONDS = 60.0
# An toàn: slot concurrency của request chết/treo sẽ tự được dọn sau ngần này giây
# (phòng leak khi client ngắt giữa chừng mà generator không chạy finally).
_CONCURRENCY_STALE_SECONDS = 300.0


class RateLimiterUnavailable(RuntimeError):
    """Raised when the configured shared limiter cannot be reached."""


def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


class InMemoryRateLimiter:
    """Process-local limiter — dùng cho dev/test (không chia sẻ giữa nhiều worker)."""

    def __init__(
        self,
        max_requests_per_minute: int,
        *,
        max_requests_per_ip_per_minute: int | None = None,
        max_requests_global_per_minute: int | None = None,
        max_concurrent_per_user: int | None = None,
    ) -> None:
        self._max_user = max_requests_per_minute
        self._max_ip = max_requests_per_ip_per_minute
        self._max_global = max_requests_global_per_minute
        self._max_concurrent = max_concurrent_per_user
        self._windows: dict[str, deque[float]] = defaultdict(deque)
        self._inflight: dict[str, set[str]] = defaultdict(set)

    async def allow(self, user_id: str, ip: str | None = None) -> bool:
        now = _now()
        scopes: list[tuple[str, int]] = [(f"user:{user_id}", self._max_user)]
        if ip and self._max_ip is not None:
            scopes.append((f"ip:{ip}", self._max_ip))
        if self._max_global is not None:
            scopes.append(("global", self._max_global))

        # Kiểm tra TẤT CẢ scope trước, chỉ ghi nhận khi mọi scope còn quota — tránh
        # đếm 1 request bị từ chối vào window của scope khác.
        for key, limit in scopes:
            self._evict(key, now)
            if len(self._windows[key]) >= limit:
                return False
        for key, _ in scopes:
            self._windows[key].append(now)
        return True

    async def acquire(self, user_id: str) -> str | None:
        if self._max_concurrent is None:
            return ""
        slots = self._inflight[user_id]
        if len(slots) >= self._max_concurrent:
            return None
        token = uuid4().hex
        slots.add(token)
        return token

    async def release(self, user_id: str, token: str | None) -> None:
        if token:
            self._inflight.get(user_id, set()).discard(token)

    def _evict(self, key: str, now: float) -> None:
        cutoff = now - _WINDOW_SECONDS
        window = self._windows[key]
        while window and window[0] < cutoff:
            window.popleft()

    def reset(self) -> None:
        self._windows.clear()
        self._inflight.clear()


# Atomic multi-scope sliding-window: dọn entry hết hạn, kiểm tra MỌI scope, chỉ ghi
# khi tất cả còn quota. KEYS = các scope key; ARGV = now, window, token, limit/scope.
_ALLOW_LUA = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local token = ARGV[3]
for i = 1, #KEYS do
  redis.call('ZREMRANGEBYSCORE', KEYS[i], 0, now - window)
  local count = redis.call('ZCARD', KEYS[i])
  if count >= tonumber(ARGV[3 + i]) then
    return 0
  end
end
for i = 1, #KEYS do
  redis.call('ZADD', KEYS[i], now, token)
  redis.call('EXPIRE', KEYS[i], math.ceil(window))
end
return 1
"""

# Concurrency acquire: dọn slot quá hạn (request chết), đếm, nhận nếu còn chỗ.
_ACQUIRE_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local stale = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local token = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now - stale)
if redis.call('ZCARD', key) >= limit then
  return 0
end
redis.call('ZADD', key, now, token)
redis.call('EXPIRE', key, math.ceil(stale))
return 1
"""


class RedisRateLimiter:
    """Shared limiter qua Redis — bắt buộc ở production (nhiều worker/instance)."""

    def __init__(
        self,
        redis_url: str,
        max_requests_per_minute: int,
        *,
        max_requests_per_ip_per_minute: int | None = None,
        max_requests_global_per_minute: int | None = None,
        max_concurrent_per_user: int | None = None,
        redis_module=None,
    ) -> None:
        self._redis_url = redis_url
        self._max_user = max_requests_per_minute
        self._max_ip = max_requests_per_ip_per_minute
        self._max_global = max_requests_global_per_minute
        self._max_concurrent = max_concurrent_per_user
        self._redis_module = redis_module
        self._client = None

    async def allow(self, user_id: str, ip: str | None = None) -> bool:
        keys: list[str] = [f"query_rate:user:{user_id}"]
        limits: list[int] = [self._max_user]
        if ip and self._max_ip is not None:
            keys.append(f"query_rate:ip:{ip}")
            limits.append(self._max_ip)
        if self._max_global is not None:
            keys.append("query_rate:global")
            limits.append(self._max_global)

        token = uuid4().hex
        args = [repr(_now()), repr(_WINDOW_SECONDS), token, *map(str, limits)]
        try:
            client = self._get_client()
            result = await client.eval(_ALLOW_LUA, len(keys), *keys, *args)
        except Exception as exc:
            raise RateLimiterUnavailable("Redis rate limiter unavailable") from exc
        return int(result) == 1

    async def acquire(self, user_id: str) -> str | None:
        if self._max_concurrent is None:
            return ""
        token = uuid4().hex
        key = f"query_concurrency:{user_id}"
        args = [repr(_now()), repr(_CONCURRENCY_STALE_SECONDS), str(self._max_concurrent), token]
        try:
            client = self._get_client()
            result = await client.eval(_ACQUIRE_LUA, 1, key, *args)
        except Exception as exc:
            raise RateLimiterUnavailable("Redis rate limiter unavailable") from exc
        return token if int(result) == 1 else None

    async def release(self, user_id: str, token: str | None) -> None:
        if not token:
            return
        try:
            await self._get_client().zrem(f"query_concurrency:{user_id}", token)
        except Exception:
            # Best-effort: slot sẽ tự hết hạn sau _CONCURRENCY_STALE_SECONDS.
            pass

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
