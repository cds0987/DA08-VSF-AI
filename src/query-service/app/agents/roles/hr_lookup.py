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


def _grounding_hint(payload: object) -> str:
    """Sự thật XÁC TÍN tính bằng CODE (không qua LLM) để chống bịa số tiền (HALLU-1/UNIT-1):
    số kỳ lương thực có + cảnh báo thiếu đơn vị. Chèn vào prompt -> LLM không thể gán '6 tháng'
    từ 1 kỳ, cũng không tự thêm USD/VND khi hồ sơ không ghi tiền tệ."""
    if not isinstance(payload, dict):
        return ""
    notes: list[str] = []
    payroll = payload.get("payroll")
    if isinstance(payroll, list) and payroll:
        periods = [str(r.get("period")) for r in payroll if isinstance(r, dict) and r.get("period")]
        has_ccy = any(isinstance(r, dict) and r.get("currency") for r in payroll)
        note = (f"- Hồ sơ CHỈ có {len(payroll)} kỳ lương: [{', '.join(periods) or 'không rõ kỳ'}]. "
                "KHÔNG cộng/ngoại suy thành số tháng khác (vd hỏi '6 tháng' nhưng chỉ có 1 kỳ -> nói rõ chỉ có 1 kỳ).")
        if not has_ccy:
            note += " Trường lương KHÔNG ghi tiền tệ -> KHÔNG tự thêm USD/VND."
        notes.append(note)
    if not notes:
        return ""
    return "[SỰ THẬT KIỂM CHỨNG — bám ĐÚNG, KHÔNG vượt]\n" + "\n".join(notes) + "\n\n"


_SALARY_KW = ("lương", "thu nhập", "salary", "payroll", "lĩnh", "thực nhận", "gross", "net", "thưởng")


def _payroll_facts(payload: object, direction: str) -> str:
    """Sự thật lương DETERMINISTIC (code) chèn THẲNG vào output worker -> synthesize LUÔN thấy
    'chỉ có N kỳ' + đơn vị, KHÔNG phụ thuộc LLM worker có nhớ caveat hay không (HALLU-1: LLM hay
    rút gọn bỏ mất 'chỉ 1 kỳ' -> downstream gán '6 tháng'). Chỉ chèn khi định hướng hỏi về lương."""
    if not isinstance(payload, dict) or not direction:
        return ""
    if not any(k in direction.lower() for k in _SALARY_KW):
        return ""
    payroll = payload.get("payroll")
    if not isinstance(payroll, list) or not payroll:
        return ""
    has_ccy = any(isinstance(r, dict) and r.get("currency") for r in payroll)
    rows = []
    for r in payroll:
        if not isinstance(r, dict):
            continue
        parts = [f"kỳ {r.get('period', '?')}"]
        for k in ("gross_salary", "net_salary", "deductions"):
            if r.get(k) is not None:
                parts.append(f"{k}={r[k]}")
        rows.append("; ".join(parts))
    unit = "" if has_ccy else " ĐƠN VỊ KHÔNG ghi trong hồ sơ (đừng tự thêm USD/VND)."
    return (f"[LƯƠNG — SỰ THẬT HỒ SƠ] Chỉ có {len(payroll)} kỳ lương: " + " | ".join(rows)
            + f".{unit} KHÔNG có dữ liệu nhiều tháng hơn -> nếu user hỏi 'tổng N tháng' mà N>"
            f"{len(payroll)}, PHẢI nói rõ hồ sơ chỉ có {len(payroll)} kỳ, KHÔNG tự cộng/ngoại suy.\n")


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
                "còn lại: 12 ngày'). TUYỆT ĐỐI KHÔNG trả số trơ không nhãn. KHÔNG diễn giải dài.\n"
                "CHỐNG BỊA SỐ (BẮT BUỘC):\n"
                "- KHÔNG cộng/gộp/ngoại suy số liệu qua nhiều kỳ. Định hướng hỏi 'tổng N tháng' "
                "nhưng hồ sơ chỉ có M kỳ -> trả đúng từng kỳ CÓ THẬT + nói rõ 'hồ sơ chỉ có M kỳ', "
                "TUYỆT ĐỐI không tự nhân/cộng thành N tháng.\n"
                "- KHÔNG tự thêm hay đổi đơn vị tiền tệ. Trường lương KHÔNG ghi tiền tệ -> giữ NGUYÊN "
                "số + ghi '(đơn vị không nêu trong hồ sơ)'. KHÔNG suy đoán USD/VND/quy đổi tỷ giá.\n"
                "- Định hướng đòi dữ liệu KHÔNG có trong hồ sơ -> trả 'Hồ sơ không có thông tin này', "
                "KHÔNG bịa con số."
            ),
            user=f"Định hướng: {task.direction or 'tóm tắt hồ sơ'}\n\n"
                 f"{_grounding_hint(payload)}Hồ sơ HR:\n{profile_json}",
            tracer=ctx.tracer, trace=ctx.trace, node=self.name,
        )
        # model lỗi/rỗng -> đưa full profile (synth deepseek tự hiểu) thay vì mất ngữ cảnh.
        body = extracted or profile_json
        # CHÈN sự thật lương deterministic LÊN ĐẦU -> synthesize không thể bịa '6 tháng' dù worker
        # LLM rút gọn bỏ caveat (HALLU-1).
        facts = _payroll_facts(payload, task.direction or "")
        return WorkerOutput(task.step_id, self.name, (facts + body) if facts else body, status="ok")
