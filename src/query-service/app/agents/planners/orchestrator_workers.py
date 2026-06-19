"""Orchestrator (router=deepseek-pro): 1 call -> Plan có cấu trúc.

route=light: trả lời thẳng (không fetch data). route=heavy: phân rã steps + DAG, mỗi step
gán role TỪ catalog + direction riêng. Parse JSON -> Plan.model_validate; sai -> retry 1 lần
(feed lỗi). Mọi lỗi -> fallback plan heavy 1-step rag_retrieve (an toàn, không vỡ).
"""
from __future__ import annotations

import json
import logging

from app.agents.plan_schema import Plan
from app.agents.planners.base import PlanContext, Planner
from app.agents.registry import register_planner
from app.agents.roles._llm import acomplete

logger = logging.getLogger(__name__)

_SYSTEM = """\
Bạn là ORCHESTRATOR điều phối trợ lý nội bộ VinSmartFuture. Nhận câu hỏi nhân viên và LẬP KẾ HOẠCH.

Quyết định route:
- "light": KHÔNG cần dữ liệu nội bộ (chào hỏi, hỏi lại hội thoại, từ chối, trả lời từ ngữ cảnh). Trả answer_hint ngắn.
- "heavy": cần truy xuất tài liệu/HR/phân tích. Phân rã thành các step.

Khi heavy, mỗi step gồm:
- id: số nguyên tăng dần từ 1
- role: CHỈ chọn trong danh sách role bên dưới
- input: query con (rag) hoặc tham số (hr)
- direction: hướng dẫn NGẮN, mệnh lệnh cho worker (vd "trích điều khoản + nguồn", "chỉ trả số liệu")
- depends_on: [] nếu độc lập (chạy song song); [id...] nếu cần kết quả step khác

QUY TẮC:
- Các step độc lập (depends_on rỗng) sẽ chạy SONG SONG -> tách retrieval/HR thành step riêng.
- LUÔN kết thúc bằng đúng 1 step role "synthesize_recommend" depends_on mọi step dữ liệu.
- Câu hỏi đơn giản chỉ cần 1 retrieval: 1 step rag_retrieve + 1 step synthesize_recommend.

- "reasoning": 1-2 câu NGẮN tiếng Việt nói rõ BẠN HIỂU câu hỏi là gì + VÌ SAO chọn plan này
  (đây là phần "suy nghĩ" hiển thị cho người dùng — viết tự nhiên, dễ hiểu).

CHỈ trả JSON đúng schema, không giải thích thêm:
{"route":"light|heavy","reasoning":"...","answer_hint":"...","steps":[{"id":1,"role":"...","input":"...","direction":"...","depends_on":[]}]}
"""


def _catalog_text(ctx: PlanContext) -> str:
    lines = []
    for r in ctx.role_catalog:
        tools = f" (tools: {', '.join(r.tools)})" if r.tools else ""
        desc = f" — {r.description}" if r.description else ""
        lines.append(f"- {r.name}{tools}{desc}")
    return "\n".join(lines) or "- (không có role)"


def _extract_json(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1] if "```" in t[3:] else t.strip("`")
        t = t[4:] if t.lower().startswith("json") else t
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("không tìm thấy JSON")
    return json.loads(t[start : end + 1])


def _fallback_plan() -> Plan:
    """Khi orchestrator lỗi hoàn toàn: heavy 1-step rag + synthesize (vẫn trả lời được)."""
    return Plan.model_validate({
        "route": "heavy",
        "steps": [
            {"id": 1, "role": "rag_retrieve", "input": "", "direction": "tìm tài liệu liên quan", "depends_on": []},
            {"id": 2, "role": "synthesize_recommend", "input": "", "direction": "tổng hợp trả lời", "depends_on": [1]},
        ],
    })


@register_planner("orchestrator_workers")
class OrchestratorWorkersPlanner(Planner):
    name = "orchestrator_workers"

    async def plan(self, ctx: PlanContext) -> Plan:
        model = ctx.make_model("think") if ctx.make_model else None
        if model is None:
            logger.warning("orchestrator no model -> fallback plan")
            return self._with_question(_fallback_plan(), ctx.question)

        valid_roles = {r.name for r in ctx.role_catalog}
        user = f"DANH SÁCH ROLE:\n{_catalog_text(ctx)}\n\nCÂU HỎI: {ctx.question}"
        err_hint = ""
        for attempt in range(2):
            text = await acomplete(model, _SYSTEM, user + err_hint)
            if not text:
                continue
            try:
                data = _extract_json(text)
                plan = Plan.model_validate(data)
                bad = [s.role for s in plan.steps if s.role not in valid_roles]
                if bad:
                    raise ValueError(f"role không có trong catalog: {bad}")
                return self._with_question(plan, ctx.question)
            except Exception as exc:  # noqa: BLE001
                logger.warning("orchestrator parse fail (attempt %d): %s", attempt, str(exc)[:160])
                err_hint = f"\n\nLỖI lần trước: {str(exc)[:200]}. Trả JSON ĐÚNG schema, role hợp lệ."
        logger.error("orchestrator failed 2 attempts -> fallback plan")
        return self._with_question(_fallback_plan(), ctx.question)

    @staticmethod
    def _with_question(plan: Plan, question: str) -> Plan:
        """Bơm câu hỏi gốc vào step rỗng input (rag/synthesize) để worker có ngữ cảnh."""
        for s in plan.steps:
            if (s.input is None or s.input == "") and s.role in ("rag_retrieve", "synthesize_recommend"):
                s.input = question
        return plan
