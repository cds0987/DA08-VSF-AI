"""Role analyze: phân tích/so sánh/tính toán trên output các step upstream (KHÔNG gọi tool).

Worker mini. Nhận upstream outputs + direction -> trả phân tích. Không có model -> nối raw.
"""
from __future__ import annotations

import json

from app.agents.base import AgentRole, WorkerInput, WorkerOutput
from app.agents.registry import register_agent
from app.agents.roles._llm import acomplete


@register_agent("analyze")
class AnalyzeRole(AgentRole):
    name = "analyze"
    capability = "worker"
    tools = ()

    async def run(self, task: WorkerInput) -> WorkerOutput:
        upstream = "\n\n".join(
            f"[step {dep}]\n{out}" for dep, out in sorted(task.upstream.items())
        ) or json.dumps(task.input, ensure_ascii=False)

        model = self.ctx.make_model(self.capability) if self.ctx.make_model else None
        result = await acomplete(
            model,
            system="Bạn là chuyên viên phân tích. Phân tích dữ liệu theo định hướng, nêu kết luận rõ ràng.",
            user=f"Định hướng: {task.direction}\n\nDữ liệu:\n{upstream}",
        )
        if result is None:
            # Không có model: trả dữ liệu thô để synthesize tự xử.
            return WorkerOutput(task.step_id, self.name, upstream, status="ok")
        return WorkerOutput(task.step_id, self.name, result, status="ok")
