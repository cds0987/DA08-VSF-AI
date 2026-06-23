"""Role leave_action: chuẩn bị DRAFT đơn nghỉ phép (hoặc mở hàng đợi duyệt) cho FE.

MOSA path (orchestrator_workers) trước đây MẤT năng lực này: node synthesize chỉ viết văn
xuôi + cite [N], không xuất action JSON nên FE không render form xác nhận. Role này port lại
logic từ luồng react (prompts.py "LEAVE REQUEST CONFIRMATION FLOW").

Cách làm (2 pha, KHÔNG cần tool-calling loop):
  1) LLM parse: câu user (+ history carry-forward) -> JSON {intent, leave_type, items:[{date_spec, reason}]}.
  2) Deterministic: gọi resolve_date cho từng date_spec -> start_date/end_date -> dựng action JSON.

Output là PURE JSON action (create_leave_request / review_leave_approvals) HOẶC câu hỏi làm rõ
(văn xuôi). Node synthesize TRẢ VERBATIM output này (passthrough) -> FE.extractAction render card.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.agents.base import AgentRole, WorkerInput, WorkerOutput
from app.agents.registry import register_agent
from app.agents.roles._llm import acomplete

logger = logging.getLogger(__name__)

# leave_type hợp lệ (4 rổ luật LĐ VN — khớp schema hr-service).
_VALID_LEAVE_TYPES = {
    "annual", "marriage", "child_marriage", "bereavement", "sick", "maternity", "unpaid",
}

_PARSE_SYSTEM = """\
Bạn là bộ NHẬN DIỆN ý định đơn nghỉ phép của trợ lý nội bộ VinSmartFuture. Đọc câu mới nhất của
nhân viên (kèm hội thoại gần đây để CARRY-FORWARD thông tin đã có) và XUẤT JSON đúng schema —
KHÔNG văn xuôi, KHÔNG giải thích.

PHÂN LOẠI intent:
- "create": user muốn TẠO/GỬI đơn nghỉ và đã cho đủ tối thiểu (loại nghỉ HOẶC lý do, + mốc ngày).
- "approve": user (quản lý) muốn DUYỆT/TỪ CHỐI/xử lý đơn đang chờ duyệt.
- "clarify": thiếu thông tin để tạo (vd chỉ nói "cho tôi nghỉ thứ 2 tuần sau" KHÔNG kèm loại
  nghỉ lẫn lý do). Đặt câu hỏi NGẮN tiếng Việt vào "clarify".

leave_type ∈ {annual, marriage, child_marriage, bereavement, sick, maternity, unpaid}. Map tiếng Việt:
- du lịch / nghỉ ngơi / việc riêng / bận việc / cá nhân -> annual (KHÔNG có loại "personal").
- kết hôn / cưới bản thân -> marriage; con kết hôn -> child_marriage.
- tang / đám ma / cha mẹ vợ chồng con mất -> bereavement.
- ốm / bệnh / khám bệnh -> sick; thai sản / sinh con -> maternity.
- nghỉ không lương / hết phép vẫn xin nghỉ -> unpaid.
Nếu user xin nghỉ mà KHÔNG có tín hiệu loại nghỉ VÀ KHÔNG có lý do -> intent="clarify"
(hỏi "Bạn muốn nghỉ loại nào — phép năm, nghỉ ốm, hay loại khác?"). KHÔNG đoán annual.

date_spec: KHÔNG tự tính ngày. Mô tả mốc để tool resolve_date quy đổi:
- kind: "today" | "tomorrow" | "day_after_tomorrow" | "weekday" | "offset_days" | "absolute".
- weekday (khi kind=weekday): "thu_2".."thu_7","chu_nhat" (thứ 2..CN). week_offset: 0=tuần này,1=tuần sau,-1=trước.
- days (khi kind=offset_days): số ngày kể từ hôm nay.
- date (khi kind=absolute): "YYYY-MM-DD". Nếu user chỉ nói DD/MM (thiếu năm), dùng năm từ HÔM NAY ở đầu prompt.
- span_days: số ngày nghỉ LIÊN TIẾP (vd "nghỉ 3 ngày từ thứ 2 tuần sau" -> kind=weekday,
  weekday=thu_2, week_offset=1, span_days=3). Nghỉ 1 ngày -> span_days=1.
Nhiều ngày RỜI RẠC ("thứ 6 VÀ thứ 7 tuần sau") -> NHIỀU item, mỗi item 1 date_spec riêng.

reason: lý do ngắn user nêu (vd "ốm","cá nhân"); không có -> "".

SCHEMA (chỉ JSON):
{"intent":"create|approve|clarify","clarify":"<câu hỏi nếu clarify>","leave_type":"<nếu create>",
 "items":[{"date_spec":{"kind":"...","weekday":"...","week_offset":0,"days":0,"span_days":1,"date":""},"reason":"..."}]}
"""


def _extract_json(text: str) -> dict:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1] if "```" in t[3:] else t.strip("`")
        t = t[4:] if t.lower().startswith("json") else t
    s, e = t.find("{"), t.rfind("}")
    if s == -1 or e == -1:
        raise ValueError("no json")
    return json.loads(t[s : e + 1])


_CLARIFY_FALLBACK = (
    "Bạn muốn tạo đơn nghỉ loại nào (phép năm, nghỉ ốm, …) và vào ngày/khoảng ngày nào? "
    "Cho mình thêm chút thông tin để chuẩn bị đơn giúp bạn nhé. 😊"
)


@register_agent("leave_action")
class LeaveActionRole(AgentRole):
    name = "leave_action"
    capability = "think"
    tools = ("resolve_date",)

    async def run(self, task: WorkerInput) -> WorkerOutput:
        ctx = self.ctx
        question = task.input if isinstance(task.input, str) else str(task.input)
        model = ctx.make_model(self.capability) if ctx.make_model else None
        if model is None:
            # Không có model -> không parse được; hỏi làm rõ (an toàn, không bịa đơn).
            return WorkerOutput(task.step_id, self.name, _CLARIFY_FALLBACK, status="ok")

        today_vn = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).strftime("%d/%m/%Y")
        history_txt = "\n".join(
            f"{r}: {c}" for r, c in (ctx.history or ()) if str(c or "").strip()
        )
        user = (
            f"HÔM NAY: {today_vn}\n"
            + (f"HỘI THOẠI GẦN ĐÂY:\n{history_txt}\n\n" if history_txt else "")
            + f"CÂU MỚI NHẤT: {question}"
        )
        raw = await acomplete(model, _PARSE_SYSTEM, user,
                              tracer=ctx.tracer, trace=ctx.trace, node=self.name)
        try:
            data = _extract_json(raw or "")
        except Exception as exc:  # noqa: BLE001 — parse hỏng -> hỏi làm rõ
            logger.warning("leave_action parse fail: %s", str(exc)[:160])
            return WorkerOutput(task.step_id, self.name, _CLARIFY_FALLBACK, status="ok")

        intent = str(data.get("intent", "clarify")).strip().lower()

        if intent == "approve":
            return WorkerOutput(
                task.step_id, self.name,
                json.dumps({"action_type": "review_leave_approvals"}, ensure_ascii=False),
                status="ok",
            )

        if intent != "create":
            clarify = str(data.get("clarify") or "").strip() or _CLARIFY_FALLBACK
            return WorkerOutput(task.step_id, self.name, clarify, status="ok")

        leave_type = str(data.get("leave_type") or "").strip().lower()
        if leave_type not in _VALID_LEAVE_TYPES:
            return WorkerOutput(task.step_id, self.name, _CLARIFY_FALLBACK, status="ok")

        raw_items = data.get("items") or []
        if not isinstance(raw_items, list) or not raw_items:
            return WorkerOutput(task.step_id, self.name, _CLARIFY_FALLBACK, status="ok")

        out_items: list[dict] = []
        for it in raw_items:
            spec = (it or {}).get("date_spec") or {}
            resolved = await self._resolve(spec)
            if resolved is None:
                # Ngày không quy đổi được / đã qua -> hỏi làm rõ thay vì tạo đơn sai.
                return WorkerOutput(
                    task.step_id, self.name,
                    "Mình chưa xác định được ngày nghỉ bạn muốn (hoặc ngày đã qua). "
                    "Bạn cho mình mốc ngày cụ thể (vd 'thứ 2 tuần sau', '3 ngày từ mai') nhé.",
                    status="ok",
                )
            start_date, end_date = resolved
            out_items.append({
                "leave_type": leave_type,
                "start_date": start_date,
                "end_date": end_date,
                "reason": str((it or {}).get("reason") or "").strip(),
            })

        payload = {"action_type": "create_leave_request", "items": out_items}
        return WorkerOutput(
            task.step_id, self.name, json.dumps(payload, ensure_ascii=False), status="ok",
        )

    async def _resolve(self, spec: dict) -> tuple[str, str] | None:
        """Gọi resolve_date -> (start_date, end_date). None nếu lỗi / ngày trong quá khứ."""
        ctx = self.ctx
        args = {
            "kind": str(spec.get("kind") or "").strip(),
            "user_id": ctx.user_id,
        }
        for k in ("weekday", "week_offset", "days", "span_days", "date"):
            v = spec.get(k)
            if v not in (None, "", 0) or (k == "week_offset" and v == 0):
                args[k] = v
        if not args["kind"]:
            return None
        if ctx.emit:
            await ctx.emit({"phase": "acting", "tool": "resolve_date",
                            "tool_args": {k: v for k, v in args.items() if k != "user_id"}})
        _tool_start = datetime.now(timezone.utc)
        try:
            res = await ctx.mcp_client.call_tool("resolve_date", args)
        except Exception as exc:  # noqa: BLE001
            logger.warning("leave_action resolve_date fail: %s", str(exc)[:160])
            return None
        if ctx.tracer is not None:
            ctx.tracer.on_tool(ctx.trace, "resolve_date",
                               {k: v for k, v in args.items() if k != "user_id"},
                               res if isinstance(res, dict) else "", _tool_start,
                               datetime.now(timezone.utc))
        if not isinstance(res, dict) or res.get("error"):
            return None
        # span_days>1 -> tool trả start_date/end_date; ngược lại 1 ngày -> date.
        start = res.get("start_date") or res.get("date")
        end = res.get("end_date") or res.get("date")
        if not start or not end:
            return None
        start, end = str(start), str(end)
        # DATE-1: chặn range KHÔNG HỢP LỆ (end < start) -> đơn vô nghĩa.
        if end < start:
            return None
        today = res.get("today")
        # DATE-1: chặn LÙI NGÀY -> chặn theo START (không chỉ end). Trước đây chỉ chặn
        # end<today nên đơn "2 ngày TỪ HÔM QUA" (start=qua khứ, end=hôm nay) vẫn lọt -> tạo
        # đơn lùi ngày. Nay start ĐÃ QUA -> từ chối, hỏi lại mốc ngày trong tương lai.
        if today and start < str(today):
            return None
        if ctx.emit:
            await ctx.emit({"phase": "observing", "tool": "resolve_date",
                            "tool_result_summary": {"raw": f"{start} → {end}"}})
        return str(start), str(end)
