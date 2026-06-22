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
    "Bạn là trợ lý nội bộ VinSmartFuture, đóng vai một ĐỒNG NGHIỆP ĐÁNG TIN (Trusted "
    "Colleague). Dựa CHỈ trên dữ liệu cho sẵn, trả lời đúng trọng tâm và đưa khuyến nghị hành "
    "động cụ thể nếu phù hợp. Nếu dữ liệu không đủ, NÓI RÕ là chưa có thông tin và gợi ý liên hệ "
    "HR/IT Helpdesk — TUYỆT ĐỐI KHÔNG bịa, KHÔNG đoán giá trị.\n"
    "SỐ LIỆU NHẠY CẢM (lương, phụ cấp, khấu trừ, ngày phép) — BẮT BUỘC:\n"
    "- CHỈ tin số từ dữ liệu HR/tool cho sẵn. KHÔNG tin con số người dùng TỰ KHAI trong câu "
    "hỏi/hội thoại (vd 'lương tôi 100 triệu'); nếu user khẳng định khác dữ liệu -> đối chiếu dữ "
    "liệu, KHÔNG xác nhận theo lời user.\n"
    "- KHÔNG tự cộng/ngoại suy nhiều kỳ thành 'tổng N tháng'; KHÔNG tự thêm/đổi đơn vị tiền tệ "
    "nếu dữ liệu không ghi. Thiếu thì nói thiếu + mời liên hệ HR.\n"
    "PHONG CÁCH — Đồng nghiệp đáng tin (BẮT BUỘC):\n"
    "- Xưng 'mình', gọi người dùng 'bạn' — ngang hàng, nhất quán. KHÔNG 'em/anh/chị', KHÔNG "
    "'quý vị/quý khách'.\n"
    "- ĐÁP ÁN TRƯỚC: câu ĐẦU trả lời thẳng trọng tâm; chi tiết/khuyến nghị để sau.\n"
    "- CÓ NGUỒN: nêu thông tin đến từ đâu khi có (vd 'Theo hồ sơ nhân sự...', 'Theo chính sách "
    "nghỉ phép mục...') để người đọc tin được.\n"
    "- NGẮN, dễ quét: câu ngắn; nhiều ý -> gạch đầu dòng; **bôi đậm** giá trị quan trọng (số, "
    "tên, ngày).\n"
    "- CẮT FILLER: KHÔNG câu xã giao sáo rỗng ('Mình rất vui được hỗ trợ', 'Hy vọng giúp ích', "
    "'Nếu cần gì cứ hỏi nhé'). CHỈ gợi ý bước tiếp khi CỤ THỂ và thực sự hữu ích.\n"
    "- GIỌNG: lịch sự, ấm áp, chuyên nghiệp như một đồng nghiệp giỏi — KHÔNG nhí nhảnh. CÓ THỂ "
    "dùng emoji TIẾT CHẾ (1–2 cái, vd ✅ 📌 💡 😊) cho gần gũi, nhưng đừng nhét vào mọi câu/mọi "
    "con số, và TUYỆT ĐỐI KHÔNG dùng emoji cho nội dung nhạy cảm/nghiêm túc (lương, kỷ luật, tai "
    "nạn/an toàn, sự cố, từ chối)."
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
