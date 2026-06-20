"""Role critic: đánh giá câu trả lời tổng hợp có bám dữ liệu + đúng trọng tâm không.

Mặc định TẮT (agents.yaml enabled:false). Khi bật, graph (feedback loop) gọi critic sau
synthesize: PASS -> trả lời; FAIL (<=max_replan) -> orchestrate lại. Output JSON {verdict, reason}.
"""
from __future__ import annotations

import json
import logging

from app.agents.base import AgentRole, WorkerInput, WorkerOutput
from app.agents.registry import register_agent
from app.agents.roles._llm import acomplete

logger = logging.getLogger(__name__)


@register_agent("critic")
class CriticRole(AgentRole):
    name = "critic"
    capability = "worker"
    tools = ()

    async def run(self, task: WorkerInput) -> WorkerOutput:
        # task.input = câu hỏi gốc; task.upstream = {0: draft_answer, ...: dữ liệu}
        draft = task.upstream.get(0, "")
        evidence = "\n".join(
            f"[{k}] {v}" for k, v in sorted(task.upstream.items()) if k != 0
        )
        model = self.ctx.make_model(self.capability) if self.ctx.make_model else None
        text = await acomplete(
            model,
            system=(
                "Bạn là người phản biện. Kiểm tra câu trả lời có (1) bám dữ liệu bằng chứng, "
                "(2) đúng trọng tâm câu hỏi, (3) không bịa. Trả JSON {\"verdict\":\"pass|fail\",\"reason\":\"...\"}."
            ),
            user=f"Câu hỏi: {task.input}\n\nCâu trả lời:\n{draft}\n\nBằng chứng:\n{evidence}",
            tracer=self.ctx.tracer, trace=self.ctx.trace, node=self.name,
        )
        verdict = "pass"  # fail-open: critic lỗi KHÔNG chặn câu trả lời
        reason = ""
        if text:
            try:
                start, end = text.find("{"), text.rfind("}")
                data = json.loads(text[start : end + 1])
                verdict = "fail" if str(data.get("verdict", "pass")).lower() == "fail" else "pass"
                reason = str(data.get("reason", ""))[:300]
            except Exception as exc:  # noqa: BLE001
                logger.warning("critic parse fail -> pass: %s", str(exc)[:120])
        return WorkerOutput(task.step_id, self.name, {"verdict": verdict, "reason": reason}, status="ok")
