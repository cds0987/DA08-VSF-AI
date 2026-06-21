"""build_memory_client — dựng MemoryClient in-process. Redis có -> RedisStmStore; không -> NoOp.

MEMORY_ENABLED=false -> trả None -> orchestration BỎ QUA memory (về hành vi cũ) = rollback an toàn
(default-off được, như mode=react). dialogue_loader + make_model inject từ dependencies.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.agents.memory.client import InProcessMemoryClient
from app.agents.memory.redis_store import NoOpStmStore, RedisStmStore

DialogueLoader = Callable[[str, str | None], Awaitable[list[tuple[str, str]]]]


def build_memory_client(
    settings: Any,
    *,
    dialogue_loader: DialogueLoader,
    make_model: Callable[[str], Any] | None,
) -> InProcessMemoryClient | None:
    if not bool(getattr(settings, "memory_enabled", True)):
        return None
    redis_url = (getattr(settings, "redis_url", "") or "").strip()
    store = RedisStmStore(redis_url) if redis_url else NoOpStmStore()
    return InProcessMemoryClient(
        stm_store=store,
        dialogue_loader=dialogue_loader,
        make_model=make_model,
        recent_n=int(getattr(settings, "memory_recent_n", 7)),
        summarize_after=int(getattr(settings, "memory_summarize_after", 12)),
    )
