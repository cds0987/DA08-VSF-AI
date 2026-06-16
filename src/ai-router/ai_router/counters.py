"""Counters — state SỐNG cho phân bố tải + quota (PLAN §5.2, §5.6, §5.7).

Router stateless -> mọi state ở đây (Redis), nhiều instance chia sẻ. reserve() NGUYÊN TỬ
(Lua) chống X user đồng thời cùng vượt trần. Không có Redis -> MemoryCounters (dev/test, 1 process).

Buckets:
  rpm:{key}:{YYYYMMDDHHMM}    requests phút này   TTL 90s
  quota_tok:{key}:{YYYYMMDD}  tokens hôm nay      TTL 26h   (OpenAI)
  req_day:{key}:{YYYYMMDD}    requests hôm nay    TTL 26h   (OpenRouter free)
  cost:{key}:{YYYYMM}         USD tháng này       TTL 32d
  cooldown:{key}              circuit-breaker 429  TTL ngắn
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone

RPM_TTL = 90
DAY_TTL = 93_600       # 26h
MONTH_TTL = 2_764_800  # 32d


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _daily_key(kind: str, key_id: str, day: str) -> str | None:
    if kind == "tokens_per_day":
        return f"quota_tok:{key_id}:{day}"
    if kind == "requests_per_day":
        return f"req_day:{key_id}:{day}"
    return None


def _daily_amount(kind: str, est_tokens: int) -> int:
    if kind == "tokens_per_day":
        return est_tokens
    if kind == "requests_per_day":
        return 1
    return 0


class Counters(ABC):
    @abstractmethod
    async def reserve(self, key_id: str, *, rpm_limit: int | None,
                      daily_kind: str, daily_limit: float, est_tokens: int) -> bool: ...

    @abstractmethod
    async def account(self, key_id: str, *, daily_kind: str,
                      est_tokens: int, real_tokens: int, cost: float | None) -> None: ...

    @abstractmethod
    async def set_cooldown(self, key_id: str, seconds: int) -> None: ...

    @abstractmethod
    async def in_cooldown(self, key_id: str) -> bool: ...

    @abstractmethod
    async def set_model_cooldown(self, model_id: str, seconds: int) -> None: ...

    @abstractmethod
    async def in_model_cooldown(self, model_id: str) -> bool: ...

    @abstractmethod
    async def usage(self, key_id: str, daily_kind: str) -> dict: ...

    @abstractmethod
    async def get_active(self, name: str) -> int: ...

    @abstractmethod
    async def set_active(self, name: str, idx: int) -> None: ...


# --------------------------------------------------------------------------- #
# Redis backend — reserve qua Lua (atomic)
# --------------------------------------------------------------------------- #
_RESERVE_LUA = """
local rpm_limit = tonumber(ARGV[1])
local daily_limit = tonumber(ARGV[2])
local amount = tonumber(ARGV[3])
if rpm_limit >= 0 then
  local cur = tonumber(redis.call('GET', KEYS[1]) or '0')
  if cur + 1 > rpm_limit then return 0 end
end
if daily_limit >= 0 then
  local d = tonumber(redis.call('GET', KEYS[2]) or '0')
  if d + amount > daily_limit then return 0 end
end
if rpm_limit >= 0 then
  redis.call('INCR', KEYS[1]); redis.call('EXPIRE', KEYS[1], tonumber(ARGV[4]))
end
if daily_limit >= 0 and amount > 0 then
  redis.call('INCRBY', KEYS[2], amount); redis.call('EXPIRE', KEYS[2], tonumber(ARGV[5]))
end
return 1
"""


class RedisCounters(Counters):
    def __init__(self, client) -> None:
        self._r = client
        self._reserve = client.register_script(_RESERVE_LUA)

    async def reserve(self, key_id, *, rpm_limit, daily_limit, daily_kind, est_tokens):
        now = _now()
        minute, day = now.strftime("%Y%m%d%H%M"), now.strftime("%Y%m%d")
        rpm_key = f"rpm:{key_id}:{minute}"
        dkey = _daily_key(daily_kind, key_id, day) or f"_noop:{key_id}"
        amount = _daily_amount(daily_kind, est_tokens)
        res = await self._reserve(
            keys=[rpm_key, dkey],
            args=[rpm_limit if rpm_limit is not None else -1,
                  daily_limit if daily_kind != "none" else -1,
                  amount, RPM_TTL, DAY_TTL],
        )
        return int(res) == 1

    async def account(self, key_id, *, daily_kind, est_tokens, real_tokens, cost):
        now = _now()
        day, month = now.strftime("%Y%m%d"), now.strftime("%Y%m")
        if daily_kind == "tokens_per_day":
            dkey = _daily_key(daily_kind, key_id, day)
            diff = int(real_tokens) - int(est_tokens)   # đối soát est vs thật
            if diff:
                await self._r.incrby(dkey, diff)
                await self._r.expire(dkey, DAY_TTL)
        if cost:
            ckey = f"cost:{key_id}:{month}"
            await self._r.incrbyfloat(ckey, float(cost))
            await self._r.expire(ckey, MONTH_TTL)

    async def set_cooldown(self, key_id, seconds):
        await self._r.set(f"cooldown:{key_id}", "1", ex=seconds)

    async def in_cooldown(self, key_id):
        return bool(await self._r.exists(f"cooldown:{key_id}"))

    async def set_model_cooldown(self, model_id, seconds):
        await self._r.set(f"mcooldown:{model_id}", "1", ex=seconds)

    async def in_model_cooldown(self, model_id):
        return bool(await self._r.exists(f"mcooldown:{model_id}"))

    async def usage(self, key_id, daily_kind):
        now = _now()
        minute, day, month = now.strftime("%Y%m%d%H%M"), now.strftime("%Y%m%d"), now.strftime("%Y%m")
        dkey = _daily_key(daily_kind, key_id, day)
        rpm = int(await self._r.get(f"rpm:{key_id}:{minute}") or 0)
        daily = int(await self._r.get(dkey) or 0) if dkey else 0
        cost = float(await self._r.get(f"cost:{key_id}:{month}") or 0.0)
        cooldown = bool(await self._r.exists(f"cooldown:{key_id}"))
        return {"rpm": rpm, "daily_used": daily, "cost_month": round(cost, 6), "cooldown": cooldown}

    async def get_active(self, name):
        return int(await self._r.get(f"active:{name}") or 0)

    async def set_active(self, name, idx):
        await self._r.set(f"active:{name}", int(idx))


# --------------------------------------------------------------------------- #
# In-memory backend — dev/test, 1 process. KHÔNG atomic xuyên process.
# --------------------------------------------------------------------------- #
class MemoryCounters(Counters):
    def __init__(self) -> None:
        self._d: dict[str, tuple[float, float]] = {}   # key -> (value, expire_at)
        self._cool: dict[str, float] = {}
        self._mcool: dict[str, float] = {}             # model_id -> expire_at
        self._active: dict[str, int] = {}

    def _get(self, k: str) -> float:
        v = self._d.get(k)
        if not v:
            return 0.0
        val, exp = v
        if exp and time.time() > exp:
            self._d.pop(k, None)
            return 0.0
        return val

    def _set(self, k: str, val: float, ttl: int) -> None:
        self._d[k] = (val, time.time() + ttl)

    async def reserve(self, key_id, *, rpm_limit, daily_limit, daily_kind, est_tokens):
        now = _now()
        minute, day = now.strftime("%Y%m%d%H%M"), now.strftime("%Y%m%d")
        rpm_key = f"rpm:{key_id}:{minute}"
        amount = _daily_amount(daily_kind, est_tokens)
        dkey = _daily_key(daily_kind, key_id, day)
        if rpm_limit is not None and self._get(rpm_key) + 1 > rpm_limit:
            return False
        if daily_kind != "none" and dkey and self._get(dkey) + amount > daily_limit:
            return False
        if rpm_limit is not None:
            self._set(rpm_key, self._get(rpm_key) + 1, RPM_TTL)
        if dkey and amount > 0:
            self._set(dkey, self._get(dkey) + amount, DAY_TTL)
        return True

    async def account(self, key_id, *, daily_kind, est_tokens, real_tokens, cost):
        now = _now()
        day, month = now.strftime("%Y%m%d"), now.strftime("%Y%m")
        if daily_kind == "tokens_per_day":
            dkey = _daily_key(daily_kind, key_id, day)
            self._set(dkey, self._get(dkey) + (int(real_tokens) - int(est_tokens)), DAY_TTL)
        if cost:
            ckey = f"cost:{key_id}:{month}"
            self._set(ckey, self._get(ckey) + float(cost), MONTH_TTL)

    async def set_cooldown(self, key_id, seconds):
        self._cool[key_id] = time.time() + seconds

    async def in_cooldown(self, key_id):
        exp = self._cool.get(key_id)
        if exp and time.time() < exp:
            return True
        self._cool.pop(key_id, None)
        return False

    async def set_model_cooldown(self, model_id, seconds):
        self._mcool[model_id] = time.time() + seconds

    async def in_model_cooldown(self, model_id):
        exp = self._mcool.get(model_id)
        if exp and time.time() < exp:
            return True
        self._mcool.pop(model_id, None)
        return False

    async def usage(self, key_id, daily_kind):
        now = _now()
        minute, day, month = now.strftime("%Y%m%d%H%M"), now.strftime("%Y%m%d"), now.strftime("%Y%m")
        dkey = _daily_key(daily_kind, key_id, day)
        return {
            "rpm": int(self._get(f"rpm:{key_id}:{minute}")),
            "daily_used": int(self._get(dkey)) if dkey else 0,
            "cost_month": round(self._get(f"cost:{key_id}:{month}"), 6),
            "cooldown": await self.in_cooldown(key_id),
        }

    async def get_active(self, name):
        return self._active.get(name, 0)

    async def set_active(self, name, idx):
        self._active[name] = int(idx)


def create_counters(redis_url: str | None) -> Counters:
    if not redis_url:
        return MemoryCounters()
    import redis.asyncio as aioredis  # noqa: PLC0415
    client = aioredis.from_url(redis_url, decode_responses=True)
    return RedisCounters(client)
