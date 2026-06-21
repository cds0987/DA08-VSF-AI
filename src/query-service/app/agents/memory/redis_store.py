"""STM store cho task_state + working_set — Redis, scope theo conversation, KHÓA gồm user_id (ACL).

Khóa: mem:task:{user_id}:{conv_id} | mem:ws:{user_id}:{conv_id}. user_id TRONG khóa -> KHÔNG rò
chéo user (ACL gate). TTL = đời phiên (mặc định 1h) -> ephemeral, hết phiên tự bỏ (không stale dài).
Mọi lỗi Redis -> nuốt (best-effort): memory hỏng KHÔNG được làm vỡ query.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.agents.memory.contracts import TaskState, WorkingSetDigest, WorkingSetItem

logger = logging.getLogger(__name__)

_DEFAULT_TTL = 3600  # đời phiên ~1h


def _safe_key(*parts: str) -> str:
    # user_id/conv_id có thể None -> chuẩn hoá; ':' trong id KHÔNG cho phá khóa.
    return ":".join((p or "_").replace(":", "_") for p in parts)


class RedisStmStore:
    """Store STM (task_state + working_set) trên Redis. Khóa CÓ user_id -> ACL isolation."""

    def __init__(self, redis_url: str, ttl: int = _DEFAULT_TTL, redis_module: Any = None) -> None:
        self._redis_url = redis_url
        self._ttl = ttl
        self._redis_module = redis_module
        self._client = None

    # ---- task_state ----
    async def get_task(self, user_id: str, conv_id: str | None) -> TaskState | None:
        raw = await self._get(_safe_key("mem:task", user_id, conv_id or ""))
        if not raw:
            return None
        try:
            d = json.loads(raw)
            return TaskState(flow=d["flow"], data=d.get("data") or {},
                             missing=tuple(d.get("missing") or ()), status=d.get("status", "pending"),
                             updated_ts=float(d.get("updated_ts") or 0))
        except Exception:  # noqa: BLE001
            return None

    async def set_task(self, user_id: str, conv_id: str | None, state: TaskState | None) -> None:
        key = _safe_key("mem:task", user_id, conv_id or "")
        if state is None:
            await self._delete(key)
            return
        payload = json.dumps({"flow": state.flow, "data": state.data, "missing": list(state.missing),
                              "status": state.status, "updated_ts": state.updated_ts or time.time()},
                             ensure_ascii=False)
        await self._setex(key, payload)

    # ---- working_set ----
    async def get_ws(self, user_id: str, conv_id: str | None) -> WorkingSetDigest:
        raw = await self._get(_safe_key("mem:ws", user_id, conv_id or ""))
        if not raw:
            return WorkingSetDigest()
        try:
            arr = json.loads(raw)
            return WorkingSetDigest(items=tuple(
                WorkingSetItem(kind=i["kind"], label=i.get("label", ""), detail=i.get("detail") or {})
                for i in arr
            ))
        except Exception:  # noqa: BLE001
            return WorkingSetDigest()

    async def add_evidence(self, user_id: str, conv_id: str | None, item: WorkingSetItem) -> None:
        cur = await self.get_ws(user_id, conv_id)
        # dedupe theo (kind,label); cap 12 item digest để không phình.
        items = [i for i in cur.items if not (i.kind == item.kind and i.label == item.label)]
        items.append(item)
        items = items[-12:]
        payload = json.dumps([{"kind": i.kind, "label": i.label, "detail": i.detail} for i in items],
                             ensure_ascii=False)
        await self._setex(_safe_key("mem:ws", user_id, conv_id or ""), payload)

    async def invalidate_ws(self, user_id: str, conv_id: str | None) -> None:
        await self._delete(_safe_key("mem:ws", user_id, conv_id or ""))

    # ---- low-level (best-effort) ----
    async def _get(self, key: str) -> str | None:
        try:
            return await self._cli().get(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory_redis_get_failed: %s", str(exc)[:120])
            return None

    async def _setex(self, key: str, val: str) -> None:
        try:
            await self._cli().set(key, val, ex=self._ttl)
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory_redis_set_failed: %s", str(exc)[:120])

    async def _delete(self, key: str) -> None:
        try:
            await self._cli().delete(key)
        except Exception:  # noqa: BLE001
            pass

    def _cli(self):
        if self._client is None:
            mod = self._redis_module or _import_redis()
            self._client = mod.from_url(self._redis_url, encoding="utf-8", decode_responses=True)
        return self._client

    def reset(self) -> None:
        self._client = None


class NoOpStmStore:
    """Khi không có Redis (test/mock) -> in-memory theo process. Vẫn scope user_id (ACL)."""
    def __init__(self) -> None:
        self._task: dict[str, TaskState] = {}
        self._ws: dict[str, list[WorkingSetItem]] = {}

    async def get_task(self, user_id, conv_id):
        return self._task.get(_safe_key(user_id, conv_id or ""))

    async def set_task(self, user_id, conv_id, state):
        k = _safe_key(user_id, conv_id or "")
        if state is None:
            self._task.pop(k, None)
        else:
            self._task[k] = state

    async def get_ws(self, user_id, conv_id):
        return WorkingSetDigest(items=tuple(self._ws.get(_safe_key(user_id, conv_id or ""), [])))

    async def add_evidence(self, user_id, conv_id, item):
        k = _safe_key(user_id, conv_id or "")
        items = [i for i in self._ws.get(k, []) if not (i.kind == item.kind and i.label == item.label)]
        items.append(item)
        self._ws[k] = items[-12:]

    async def invalidate_ws(self, user_id, conv_id):
        self._ws.pop(_safe_key(user_id, conv_id or ""), None)

    def reset(self) -> None:
        self._task.clear(); self._ws.clear()


def _import_redis():
    import redis.asyncio as r
    return r
