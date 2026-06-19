"""summary_buffer: hội thoại dài -> nén phần cũ thành 1 summary + giữ K lượt gần nguyên văn.

Giải điểm yếu "chỉ K=4 message thô": hội thoại dài vẫn giữ ngữ cảnh xuyên suốt mà không
nổ token. Lỗi/không có model -> degrade về recent_buffer (cắt K gần nhất).
"""
from __future__ import annotations

import logging

from app.agents.memory.base import MemoryProvider, Message
from app.agents.registry import register_memory
from app.agents.roles._llm import acomplete

logger = logging.getLogger(__name__)


@register_memory("summary_buffer")
class SummaryBufferMemory(MemoryProvider):
    name = "summary_buffer"

    async def load(self, messages: list[Message]) -> list[Message]:
        msgs = list(messages)
        if len(msgs) <= self.summarize_after:
            return msgs[-self.keep_recent:] if self.keep_recent > 0 else msgs

        recent = msgs[-self.keep_recent:] if self.keep_recent > 0 else []
        older = msgs[: len(msgs) - len(recent)]
        if not older:
            return recent

        model = self.make_model("worker") if self.make_model else None
        convo = "\n".join(f"{r}: {c}" for r, c in older)
        summary = await acomplete(
            model,
            system="Tóm tắt hội thoại thành các sự thật/ngữ cảnh quan trọng cho lượt sau. Ngắn gọn, gạch đầu dòng.",
            user=convo,
        )
        if not summary:
            logger.warning("summary_buffer no model -> degrade recent_buffer")
            return recent
        return [("system", f"[Tóm tắt hội thoại trước]\n{summary}"), *recent]
