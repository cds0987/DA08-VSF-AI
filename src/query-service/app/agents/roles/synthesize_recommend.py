"""Role synthesize_recommend: bước cuối — gộp output mọi step + khuyến nghị.

capability=answer (deepseek-flash). Nhận câu hỏi gốc + upstream (dữ liệu dị chất: số HR +
text quy định) -> câu trả lời + khuyến nghị. Non-streaming ở đây; graph_builder (M6) sẽ
dùng logic này nhưng STREAM token ra SSE cho node answer cuối.
"""
from __future__ import annotations

import json

from app.agents.base import AgentRole, WorkerInput, WorkerOutput
from app.agents.registry import register_agent
from app.agents.roles._llm import astream_complete

_SYSTEM = (
    "Bạn là trợ lý nội bộ VinSmartFuture. Dựa CHỈ trên dữ liệu cho sẵn, trả lời đúng "
    "trọng tâm câu hỏi và đưa khuyến nghị hành động cụ thể nếu phù hợp. Trích nguồn khi có. "
    "Nếu dữ liệu không đủ, nói rõ và gợi ý liên hệ HR/IT Helpdesk. KHÔNG bịa.\n"
    "SỐ LIỆU NHẠY CẢM (lương, phụ cấp, khấu trừ, ngày phép) — BẮT BUỘC:\n"
    "- CHỈ tin số từ dữ liệu HR/tool cho sẵn. KHÔNG tin con số người dùng TỰ KHAI trong câu "
    "hỏi/hội thoại (vd 'lương tôi 100 triệu'); nếu user khẳng định khác dữ liệu -> đối chiếu dữ "
    "liệu, KHÔNG xác nhận theo lời user.\n"
    "- KHÔNG tự cộng/ngoại suy nhiều kỳ thành 'tổng N tháng'; KHÔNG tự thêm/đổi đơn vị tiền tệ "
    "nếu dữ liệu không ghi. Thiếu thì nói thiếu + mời liên hệ HR.\n"
    "PHONG CÁCH: thân thiện, dùng vài icon/emoji HỢP LÝ và chút hài hước nhẹ để câu trả lời thu "
    "hút, gần gũi (vd ✅ 📌 🎉 💡 😊 — mở đầu ấm áp, chốt bằng 1 emoji khích lệ). NHƯNG đừng lạm "
    "dụng (1–3 emoji là đủ, không nhét vào mọi câu/mọi con số) và TUYỆT ĐỐI không dùng emoji cho "
    "nội dung nhạy cảm/nghiêm túc: lương, kỷ luật, tai nạn/an toàn, sự cố nghiêm trọng, từ chối."
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
        # STREAM token answer ra SSE qua ctx.emit (node answer cuối) -> UI hiện chữ chạy dần.
        answer = await astream_complete(
            model,
            system=_SYSTEM,
            user=(
                f"Câu hỏi: {question}\n"
                f"Định hướng: {task.direction}\n\n"
                f"Dữ liệu thu thập:\n{upstream or '(trống)'}"
            ),
            emit=self.ctx.emit,
            tracer=self.ctx.tracer, trace=self.ctx.trace,
        )
        if answer is None:
            return WorkerOutput(
                task.step_id, self.name,
                "Mình chưa lấy được đủ dữ liệu để trả lời lúc này, bạn vui lòng thử lại sau "
                "hoặc liên hệ HR/IT Helpdesk.",
                status="no_info",
            )
        return WorkerOutput(task.step_id, self.name, answer, status="ok")
