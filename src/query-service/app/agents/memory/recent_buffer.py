"""recent_buffer: giữ K message gần nhất (hành vi hiện tại của query-service)."""
from __future__ import annotations

from app.agents.memory.base import MemoryProvider, Message
from app.agents.registry import register_memory


@register_memory("recent_buffer")
class RecentBufferMemory(MemoryProvider):
    name = "recent_buffer"

    async def load(self, messages: list[Message]) -> list[Message]:
        if self.keep_recent <= 0:
            return list(messages)
        return list(messages)[-self.keep_recent:]
