"""Role hr_lookup: lấy hồ sơ HR cá nhân (hr_query). user_id tiêm server-side (ACL).

Trả full profile JSON; nếu có model + direction: mini trích đúng phần được hỏi (số liệu thô).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from app.agents.base import AgentRole, WorkerInput, WorkerOutput
from app.agents.registry import register_agent
from app.agents.roles._llm import acomplete

logger = logging.getLogger(__name__)


@register_agent("hr_lookup")
class HrLookupRole(AgentRole):
    name = "hr_lookup"
    capability = "worker"
    tools = ("hr_query",)

    async def run(self, task: WorkerInput) -> WorkerOutput:
        ctx = self.ctx
        if ctx.emit:
            await ctx.emit({"phase": "acting", "tool": "hr_query",
                            "tool_args": {"intent": task.direction or "hồ sơ HR"}})
        _tool_start = datetime.now(timezone.utc)
        try:
            raw = await ctx.mcp_client.call_tool("hr_query", {"user_id": ctx.user_id})
        except Exception as exc:  # noqa: BLE001
            return WorkerOutput(task.step_id, self.name, "", status="error", error=str(exc)[:200])
        if ctx.tracer is not None:
            ctx.tracer.on_tool(ctx.trace, "hr_query", {"intent": task.direction or "hồ sơ HR"},
                               "ok" if isinstance(raw, dict) else "", _tool_start,
                               datetime.now(timezone.utc))

        if isinstance(raw, dict) and raw.get("error"):
            return WorkerOutput(task.step_id, self.name, "", status="no_info",
                                error=str(raw.get("error"))[:200])

        payload = raw.get("data", raw) if isinstance(raw, dict) else raw
        if not payload:
            return WorkerOutput(task.step_id, self.name, "", status="no_info")

        profile_json = json.dumps(payload, ensure_ascii=False)
        if ctx.emit:
            await ctx.emit({"phase": "observing", "tool": "hr_query",
                            "tool_result_summary": {"raw": "Đã lấy hồ sơ HR"}})

        model = ctx.make_model(self.capability) if ctx.make_model else None
        extracted = await acomplete(
            model,
            system=(
                "Bạn trích dữ liệu HR. Dựa CHỈ trên hồ sơ cho sẵn, trả các phần liên quan tới "
                "định hướng dưới dạng 'Nhãn: giá trị' (GIỮ tên trường + đơn vị, vd 'Số ngày phép "
                "còn lại: 12 ngày'). TUYỆT ĐỐI KHÔNG trả số trơ không nhãn. KHÔNG diễn giải dài."
            ),
            user=f"Định hướng: {task.direction or 'tóm tắt hồ sơ'}\n\nHồ sơ HR:\n{profile_json}",
            tracer=ctx.tracer, trace=ctx.trace, node=self.name,
        )
        # model lỗi/rỗng -> đưa full profile (synth deepseek tự hiểu) thay vì mất ngữ cảnh.
        return WorkerOutput(task.step_id, self.name, extracted or profile_json, status="ok")
