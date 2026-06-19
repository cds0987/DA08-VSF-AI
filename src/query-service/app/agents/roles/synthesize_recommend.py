"""Role synthesize_recommend: bước cuối — gộp output mọi step + khuyến nghị.

capability=answer (deepseek-flash). Nhận câu hỏi gốc + upstream (dữ liệu dị chất: số HR +
text quy định) -> câu trả lời + khuyến nghị. Non-streaming ở đây; graph_builder (M6) sẽ
dùng logic này nhưng STREAM token ra SSE cho node answer cuối.
"""
from __future__ import annotations

import json

from app.agents.base import AgentRole, WorkerInput, WorkerOutput
from app.agents.registry import register_agent
from app.agents.roles._llm import acomplete

_SYSTEM = (
    "Bạn là trợ lý nội bộ VinSmartFuture. Dựa CHỈ trên dữ liệu cho sẵn, trả lời đúng "
    "trọng tâm câu hỏi và đưa khuyến nghị hành động cụ thể nếu phù hợp. Trích nguồn khi có. "
    "Nếu dữ liệu không đủ, nói rõ và gợi ý liên hệ HR/IT Helpdesk. KHÔNG bịa."
)


@register_agent("synthesize_recommend")
class SynthesizeRecommendRole(AgentRole):
    name = "synthesize_recommend"
    capability = "answer"
    tools = ()

    async def run(self, task: WorkerInput) -> WorkerOutput:
        question = task.input if isinstance(task.input, str) else json.dumps(task.input, ensure_ascii=False)
        upstream = "\n\n".join(
            f"[step {dep}]\n{out}" for dep, out in sorted(task.upstream.items())
        )

        model = self.ctx.make_model(self.capability) if self.ctx.make_model else None
        answer = await acomplete(
            model,
            system=_SYSTEM,
            user=(
                f"Câu hỏi: {question}\n"
                f"Định hướng: {task.direction}\n\n"
                f"Dữ liệu thu thập:\n{upstream or '(trống)'}"
            ),
        )
        if answer is None:
            return WorkerOutput(
                task.step_id, self.name,
                "Mình chưa lấy được đủ dữ liệu để trả lời lúc này, bạn vui lòng thử lại sau "
                "hoặc liên hệ HR/IT Helpdesk.",
                status="no_info",
            )
        return WorkerOutput(task.step_id, self.name, answer, status="ok")
