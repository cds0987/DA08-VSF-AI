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

import os
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone

RPM_TTL = 90
DAY_TTL = 93_600       # 26h
MONTH_TTL = 2_764_800  # 32d
BAND_TTL = 3_600       # 1h — band là cửa sổ trượt rải tải, không cần bền
SEQ_TTL = 93_600       # 26h — bộ đếm weighted round-robin theo capability
INFLIGHT_STALE = 600   # 10' — hold treo (worker chết giữa stream) tự rớt khỏi đếm in-flight
WIDTH_TTL = 600        # 10' — width là tín hiệu SỐNG; im tải -> tự co về hẹp (rẻ lại)
TPM_TTL = 90           # cửa sổ token/phút (OpenAI có trần TPM rõ) — như RPM nhưng đếm token
# AIMD cho key OpenRouter (đa-upstream, KHÔNG có TPM cố định) -> TỰ DÒ trần qua 429.
# INIT/MAX nới được qua ENV (thử nghiệm tải: burst lạnh cần headroom > số concurrent) mà KHÔNG
# sửa code — default giữ NGUYÊN hành vi cũ (8/2/64/300). AIROUTER_AIMD_INIT=16 -> 5 OR key×16=80.
AIMD_INIT = float(os.environ.get("AIROUTER_AIMD_INIT", "8"))
AIMD_MIN = float(os.environ.get("AIROUTER_AIMD_MIN", "2"))
AIMD_MAX = float(os.environ.get("AIROUTER_AIMD_MAX", "64"))
AIMD_TTL = int(os.environ.get("AIROUTER_AIMD_TTL", "300"))


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

    # --- banded rotation (rải tải 250K/150K) + weighted round-robin ---
    @abstractmethod
    async def add_band(self, scope: str, key_id: str, amount: int) -> int: ...

    @abstractmethod
    async def get_band(self, scope: str, key_id: str) -> int: ...

    @abstractmethod
    async def reset_band(self, scope: str, key_id: str) -> None: ...

    @abstractmethod
    async def next_seq(self, name: str) -> int: ...

    # --- drain (human-in-the-loop: rút key khỏi vòng xoay, có TTL tự hết hạn) ---
    @abstractmethod
    async def set_drain(self, key_id: str, seconds: int) -> None: ...

    @abstractmethod
    async def is_drained(self, key_id: str) -> bool: ...

    @abstractmethod
    async def clear_drain(self, key_id: str) -> None: ...

    # --- in-flight concurrency + elastic width (selector elastic_banded) ---
    # Slot in-flight đồng thời per key (đo CONCURRENCY thật của stream dài — khác RPM/phút).
    # acquire trả token (None nếu key đầy slot); release theo token; get để xếp least-loaded.
    @abstractmethod
    async def acquire_inflight(self, key_id: str, *, max_inflight: int) -> str | None: ...

    @abstractmethod
    async def release_inflight(self, key_id: str, token: str | None) -> None: ...

    @abstractmethod
    async def get_inflight(self, key_id: str) -> int: ...

    # Width = số key đang active của scope (co giãn theo tải). State sống, chia sẻ qua Redis.
    @abstractmethod
    async def get_width(self, scope: str) -> int: ...

    @abstractmethod
    async def set_width(self, scope: str, n: int) -> None: ...

    # --- TPM (OpenAI: trần token/phút RÕ) ---
    @abstractmethod
    async def tpm_reserve(self, key_id: str, *, amount: int, tpm_limit: int) -> bool: ...

    @abstractmethod
    async def get_tpm(self, key_id: str) -> int: ...

    # --- AIMD adaptive limit (OpenRouter: trần DÒ qua 429, như TCP congestion) ---
    @abstractmethod
    async def get_aimd_limit(self, key_id: str) -> float: ...

    @abstractmethod
    async def aimd_grow(self, key_id: str) -> None: ...

    @abstractmethod
    async def aimd_shrink(self, key_id: str) -> None: ...


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


# In-flight acquire: ZSET per key, score=now. Dọn hold treo (> stale) -> đếm slot đang dùng;
# còn chỗ (< max) thì ZADD token. Atomic -> X request đồng thời KHÔNG vượt slot/key.
_INFLIGHT_LUA = """
local now = tonumber(ARGV[1])
local stale = tonumber(ARGV[2])
local maxn = tonumber(ARGV[3])
local token = ARGV[4]
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - stale)
if redis.call('ZCARD', KEYS[1]) >= maxn then return 0 end
redis.call('ZADD', KEYS[1], now, token)
redis.call('EXPIRE', KEYS[1], math.ceil(stale))
return 1
"""


# TPM acquire: bucket token/phút/key. cur+amount ≤ limit -> INCRBY (atomic). OpenAI có trần rõ.
_TPM_LUA = """
local lim = tonumber(ARGV[1])
local amt = tonumber(ARGV[2])
local cur = tonumber(redis.call('GET', KEYS[1]) or '0')
if cur + amt > lim then return 0 end
redis.call('INCRBY', KEYS[1], amt); redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
return 1
"""


class RedisCounters(Counters):
    def __init__(self, client) -> None:
        self._r = client
        self._reserve = client.register_script(_RESERVE_LUA)
        self._inflight = client.register_script(_INFLIGHT_LUA)
        self._tpm = client.register_script(_TPM_LUA)

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

    async def add_band(self, scope, key_id, amount):
        k = f"band:{scope}:{key_id}"
        val = await self._r.incrby(k, int(amount))
        await self._r.expire(k, BAND_TTL)
        return int(val)

    async def get_band(self, scope, key_id):
        return int(await self._r.get(f"band:{scope}:{key_id}") or 0)

    async def reset_band(self, scope, key_id):
        await self._r.delete(f"band:{scope}:{key_id}")

    async def next_seq(self, name):
        k = f"seq:{name}"
        val = await self._r.incr(k)
        await self._r.expire(k, SEQ_TTL)
        return int(val)

    async def set_drain(self, key_id, seconds):
        await self._r.set(f"drain:{key_id}", "1", ex=seconds)

    async def is_drained(self, key_id):
        return bool(await self._r.exists(f"drain:{key_id}"))

    async def clear_drain(self, key_id):
        await self._r.delete(f"drain:{key_id}")

    async def acquire_inflight(self, key_id, *, max_inflight):
        token = uuid.uuid4().hex
        res = await self._inflight(keys=[f"inflight:{key_id}"],
                                   args=[time.time(), INFLIGHT_STALE, max_inflight, token])
        return token if int(res) == 1 else None

    async def release_inflight(self, key_id, token):
        if token:
            await self._r.zrem(f"inflight:{key_id}", token)

    async def get_inflight(self, key_id):
        k = f"inflight:{key_id}"
        await self._r.zremrangebyscore(k, 0, time.time() - INFLIGHT_STALE)
        return int(await self._r.zcard(k))

    async def get_width(self, scope):
        return int(await self._r.get(f"width:{scope}") or 1)

    async def set_width(self, scope, n):
        await self._r.set(f"width:{scope}", int(n), ex=WIDTH_TTL)

    async def tpm_reserve(self, key_id, *, amount, tpm_limit):
        minute = _now().strftime("%Y%m%d%H%M")
        res = await self._tpm(keys=[f"tpm:{key_id}:{minute}"], args=[tpm_limit, amount, TPM_TTL])
        return int(res) == 1

    async def get_tpm(self, key_id):
        minute = _now().strftime("%Y%m%d%H%M")
        return int(await self._r.get(f"tpm:{key_id}:{minute}") or 0)

    async def get_aimd_limit(self, key_id):
        v = await self._r.get(f"aimd:{key_id}")
        return float(v) if v else AIMD_INIT

    async def aimd_grow(self, key_id):
        v = await self.get_aimd_limit(key_id)
        await self._r.set(f"aimd:{key_id}", min(AIMD_MAX, v + 1.0), ex=AIMD_TTL)

    async def aimd_shrink(self, key_id):
        v = await self.get_aimd_limit(key_id)
        await self._r.set(f"aimd:{key_id}", max(AIMD_MIN, v * 0.5), ex=AIMD_TTL)


# --------------------------------------------------------------------------- #
# In-memory backend — dev/test, 1 process. KHÔNG atomic xuyên process.
# --------------------------------------------------------------------------- #
class MemoryCounters(Counters):
    def __init__(self) -> None:
        self._d: dict[str, tuple[float, float]] = {}   # key -> (value, expire_at)
        self._cool: dict[str, float] = {}
        self._mcool: dict[str, float] = {}             # model_id -> expire_at
        self._active: dict[str, int] = {}
        self._drain: dict[str, float] = {}             # key_id -> expire_at (drain TTL)
        self._inflight: dict[str, list[tuple[str, float]]] = {}  # key_id -> [(token, ts)]
        self._width: dict[str, int] = {}               # scope -> số key active
        self._aimd: dict[str, float] = {}              # key_id -> adaptive limit (OpenRouter)

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

    async def add_band(self, scope, key_id, amount):
        k = f"band:{scope}:{key_id}"
        val = self._get(k) + int(amount)
        self._set(k, val, BAND_TTL)
        return int(val)

    async def get_band(self, scope, key_id):
        return int(self._get(f"band:{scope}:{key_id}"))

    async def reset_band(self, scope, key_id):
        self._d.pop(f"band:{scope}:{key_id}", None)

    async def next_seq(self, name):
        k = f"seq:{name}"
        val = int(self._get(k)) + 1
        self._set(k, val, SEQ_TTL)
        return val

    async def set_drain(self, key_id, seconds):
        self._drain[key_id] = time.time() + seconds

    async def is_drained(self, key_id):
        exp = self._drain.get(key_id)
        if exp and time.time() < exp:
            return True
        self._drain.pop(key_id, None)
        return False

    async def clear_drain(self, key_id):
        self._drain.pop(key_id, None)

    def _live_inflight(self, key_id: str) -> list[tuple[str, float]]:
        cutoff = time.time() - INFLIGHT_STALE
        lst = [t for t in self._inflight.get(key_id, []) if t[1] > cutoff]
        self._inflight[key_id] = lst
        return lst

    async def acquire_inflight(self, key_id, *, max_inflight):
        lst = self._live_inflight(key_id)
        if len(lst) >= max_inflight:
            return None
        token = uuid.uuid4().hex
        lst.append((token, time.time()))
        return token

    async def release_inflight(self, key_id, token):
        if not token:
            return
        self._inflight[key_id] = [t for t in self._inflight.get(key_id, []) if t[0] != token]

    async def get_inflight(self, key_id):
        return len(self._live_inflight(key_id))

    async def get_width(self, scope):
        return self._width.get(scope, 1)

    async def set_width(self, scope, n):
        self._width[scope] = int(n)

    async def tpm_reserve(self, key_id, *, amount, tpm_limit):
        minute = _now().strftime("%Y%m%d%H%M")
        k = f"tpm:{key_id}:{minute}"
        if self._get(k) + amount > tpm_limit:
            return False
        self._set(k, self._get(k) + amount, TPM_TTL)
        return True

    async def get_tpm(self, key_id):
        minute = _now().strftime("%Y%m%d%H%M")
        return int(self._get(f"tpm:{key_id}:{minute}"))

    async def get_aimd_limit(self, key_id):
        return self._aimd.get(key_id, AIMD_INIT)

    async def aimd_grow(self, key_id):
        self._aimd[key_id] = min(AIMD_MAX, self._aimd.get(key_id, AIMD_INIT) + 1.0)

    async def aimd_shrink(self, key_id):
        self._aimd[key_id] = max(AIMD_MIN, self._aimd.get(key_id, AIMD_INIT) * 0.5)


def create_counters(redis_url: str | None) -> Counters:
    if not redis_url:
        return MemoryCounters()
    import redis.asyncio as aioredis  # noqa: PLC0415
    client = aioredis.from_url(redis_url, decode_responses=True)
    return RedisCounters(client)
