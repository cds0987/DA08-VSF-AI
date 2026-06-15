import json


class RedisAccessCache:
    def __init__(self, redis_url: str, ttl: int = 300, redis_module=None) -> None:
        self._redis_url = redis_url
        self._ttl = ttl
        self._redis_module = redis_module
        self._client = None

    async def get(self, user_id: str) -> list[str] | None:
        key = f"acl:{user_id}"
        try:
            val = await self._get_client().get(key)
        except Exception:
            return None
        if val is None:
            return None
        return json.loads(val)

    async def set(self, user_id: str, doc_ids: list[str]) -> None:
        key = f"acl:{user_id}"
        try:
            await self._get_client().setex(key, self._ttl, json.dumps(doc_ids))
        except Exception:
            pass

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


class NoOpAccessCache:
    async def get(self, user_id: str) -> list[str] | None:
        return None

    async def set(self, user_id: str, doc_ids: list[str]) -> None:
        pass

    def reset(self) -> None:
        pass


def _import_redis_asyncio():
    try:
        import redis.asyncio as redis_asyncio
    except ImportError as exc:
        raise RuntimeError("redis>=5.0.0 is required for access cache") from exc
    return redis_asyncio
