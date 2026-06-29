"""Build LangGraph cho mode=orchestrator_workers (fan-out động theo DAG).

Graph: START -> orchestrate -> (light? synthesize : dispatch Send[worker]) ;
worker -> join -> (còn step? dispatch : synthesize) -> END.

Node functions CLOSURE quanh ctx/make_model (mcp_client KHÔNG đi vào state -> an toàn
checkpointer). Send payload chỉ mang dữ liệu step (serializable).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.agents.base import RoleContext, WorkerInput, WorkerOutput
from app.agents.bus import OrchestratorState, aggregate_sources, upstream_outputs
from app.agents.manifest import AgentsManifest
from app.agents.planners.base import PlanContext, Planner
from app.agents.registry import AGENT_REGISTRY

logger = logging.getLogger(__name__)

_SYNTH_ROLE = "synthesize_recommend"
_ACTION_ROLE = "leave_action"


def _build_data_text(data_results: dict, steps: list) -> str:
    """Gom output các worker thành THÔNG TIN ĐÃ THU THẬP cho verify_answer.

    Prefix mỗi block bằng role + direction của step tương ứng -> node cuối trích PER-DIRECTION
    trên chunks thô (thiết yếu khi worker BỎ distill: LLM cần biết aspect/khía cạnh mỗi nguồn).
    direction rỗng -> chỉ `[role]` (không thừa " · "). Vô hại cả khi distill bật.
    """
    dir_by_id = {getattr(s, "id", None): (getattr(s, "direction", "") or "") for s in (steps or [])}
    blocks = []
    for k in sorted(data_results):
        r = data_results[k]
        if not str(r.output or "").strip():
            continue
        direction = dir_by_id.get(k, "")
        label = f"{r.role} · {direction}" if direction else r.role
        blocks.append(f"[{label}] {r.output}")
    return "\n\n".join(blocks)

_SYNTH_CITE_SYSTEM = """\
Bạn là trợ lý nội bộ VinSmartFuture. Dựa CHỈ trên THÔNG TIN ĐÃ THU THẬP, trả lời đúng trọng tâm
câu hỏi + khuyến nghị hành động cụ thể nếu phù hợp. Nếu dữ liệu không đủ, nói rõ phần còn thiếu +
gợi ý liên hệ HR/IT Helpdesk. KHÔNG bịa số liệu/chính sách/ngày tháng.

== TRÍCH DẪN NGUỒN (BẮT BUỘC) ==
- DANH SÁCH NGUỒN cho sẵn ở cuối, mỗi nguồn có số [N]. Khi câu trả lời dùng thông tin từ tài liệu
  nào, CHÈN [N] NGAY SAU câu/ý đó (vd: "Nhân viên được nghỉ 12 ngày phép năm [1]."). Dùng ĐÚNG số
  trong danh sách; một câu có thể mang nhiều nguồn [1][3].
- TUYỆT ĐỐI KHÔNG viết tên file/đường dẫn trong câu trả lời — KHÔNG "(Nguồn: abc.pdf, trang 1)",
  KHÔNG để tên file trong ` `code` `, KHÔNG "mở file trực tiếp". CHỈ dùng số [N]; giao diện sẽ tự
  render thẻ nguồn BẤM ĐƯỢC từ [N].
- Nếu DANH SÁCH NGUỒN trống: KHÔNG bịa [N]; trả lời từ dữ liệu HR/kiến thức chung và nói rõ chưa
  có tài liệu nội bộ phù hợp.

== PHONG CÁCH ==
Ấm áp, chuyên nghiệp, đúng trọng tâm. Dùng vài icon/emoji hợp lý + hài hước nhẹ (✅ 📌 💡 😊) nhưng
KHÔNG lạm dụng, KHÔNG dùng cho nội dung nhạy cảm (lương/kỷ luật/an toàn/từ chối). Match ngôn ngữ
người dùng (mặc định tiếng Việt). Dùng đề mục/danh sách khi có nhiều ý.
"""


_VERIFY_SYSTEM = (
    "Bạn là bộ kiểm thông tin của trợ lý nội bộ VinSmartFuture. Dựa trên CÂU HỎI và DỮ LIỆU đã "
    "thu thập, phán định: dữ liệu ĐÃ ĐỦ để trả lời đầy đủ & chính xác câu hỏi chưa?\n"
    "- Đủ = trả lời được phần CỐT LÕI với dữ kiện cụ thể (số liệu/chính sách/bước/trạng thái); "
    "nếu tài liệu nội bộ rõ ràng KHÔNG chứa thông tin thì cũng coi là ĐỦ (để trả lời trung thực "
    "phần thiếu + gợi ý liên hệ HR/IT, tránh lặp vô ích).\n"
    "- Thiếu = còn khía cạnh CHÍNH của câu hỏi chưa có dữ liệu mà tra cứu thêm có thể lấp.\n"
    "KHÔNG tự trả lời câu hỏi. Trả PURE JSON: "
    '{"sufficient": true|false, "missing": "<ngắn>", "reason": "<ngắn>"}. Phân vân -> sufficient=true.'
)


# GỘP analyze + verify + answer -> 1 node verify_answer. Model TỔNG HỢP/PHÂN TÍCH (reasoning hiện
# ra PANEL "Verify — Kiểm tra & tổng hợp"), tự quyết: thiếu -> "<<NEED_MORE>>" (replan, mở rộng plan);
# đủ -> viết THẲNG câu trả lời + [N] (stream xuống message). 1 lần suy luận thay vì 3.
_VA_SYSTEM = """\
Bạn là trợ lý nội bộ VinSmartFuture. Dựa trên CÂU HỎI, THÔNG TIN ĐÃ THU THẬP và DANH SÁCH NGUỒN:

QUYỀN TRUY CẬP ĐÃ XÁC THỰC: Tài liệu được hệ thống truy xuất = user ĐÃ được xác thực quyền truy
cập (ACL kiểm soát trước khi tìm kiếm). TUYỆT ĐỐI KHÔNG từ chối hoặc hạn chế trả lời vì nhãn
phân loại trong NỘI DUNG tài liệu ("nội bộ", "bảo mật", "không phát tán", "confidential",
"internal only"...) — đó là nhãn quản lý tài liệu, KHÔNG phải lệnh cho AI. Phải trả lời đầy đủ
từ nội dung chunk đã thu thập.

KIỂM TRA THẦM (TUYỆT ĐỐI KHÔNG IN RA): tự đối chiếu dữ liệu với câu hỏi, phán định dữ liệu đã ĐỦ trả
lời phần CỐT LÕI chưa. Tài liệu nội bộ rõ ràng KHÔNG có thông tin -> vẫn coi là ĐỦ (trả lời trung thực
phần thiếu + gợi ý liên hệ HR/IT). Phần kiểm tra này CHỈ để bạn tự quyết, KHÔNG xuất ra cho user.

⚠️⚠️ ĐỊNH DẠNG OUTPUT — CỰC KỲ QUAN TRỌNG: chỉ in 1 trong 2 (NEED_MORE hoặc câu trả lời). TUYỆT ĐỐI
KHÔNG in phần kiểm tra/suy nghĩ. Câu trả lời PHẢI đi THẲNG vào nội dung cho nhân viên, KHÔNG mở đầu
bằng bất kỳ câu/nhãn META nào như: "BƯỚC 1/2...", "TỔNG HỢP & KIỂM TRA:", "Phân tích & Kiểm tra:",
"Tổng hợp:", "Dữ liệu đã đủ...", "Thông tin đã đủ để trả lời...", "Nội dung thu thập đã đủ...",
"Dữ liệu hiện có...". Bắt đầu NGAY bằng nội dung (vd "Chào bạn,..." hoặc "Theo quy định...").

XUẤT (chọn 1):
- CHƯA ĐỦ vì thiếu DỮ LIỆU HỆ THỐNG (tài liệu/HR) mà tra thêm SẼ lấp được -> in ĐÚNG 1 dòng bắt
  đầu "<<NEED_MORE>>" + mô tả NGẮN cần tra gì, rồi DỪNG. TUYỆT ĐỐI KHÔNG viết câu trả lời. CHỈ dùng
  khi thiếu DỮ LIỆU công cụ lấy thêm được.
  ⚠️ KHÔNG dùng <<NEED_MORE>> khi: (1) đã có tài liệu liên quan dù chưa đủ mọi khía cạnh —
  viết thẳng từ data hiện có; (2) câu hỏi chính sách chung (nghỉ phép, lương, quy trình) đã
  có doc → không cần tra thêm; (3) chỉ muốn "thêm chi tiết" — replan = +20-40s user chờ thêm.
- Câu hỏi MƠ HỒ / thiếu thông tin TỪ NGƯỜI DÙNG (vd "lên kế hoạch giúp tôi" nhưng chưa rõ kế hoạch
  GÌ; "tư vấn cho tôi" chưa rõ chủ đề) -> ĐỪNG <<NEED_MORE>> (tra thêm VÔ ÍCH, sẽ làm user CHỜ lâu).
  Trả lời NGAY: nêu phần làm được từ dữ liệu đã có + HỎI LẠI user cho rõ + gợi ý vài lựa chọn cụ thể.
- ĐỦ -> viết THẲNG câu trả lời cho nhân viên (KHÔNG nhắc <<NEED_MORE>>).

== KHI VIẾT CÂU TRẢ LỜI ==
Đúng trọng tâm + khuyến nghị hành động cụ thể.
Mỗi block THÔNG TIN gắn nhãn [role · định hướng] = một KHÍA CẠNH của câu hỏi. Hãy trích & tổng hợp
ĐỦ MỌI khía cạnh/định hướng đó (đừng bỏ sót aspect nào), vẫn giữ cite [N] cho từng ý.
NGUỒN TRẢ LỜI — theo thứ tự ưu tiên:
1. Tài liệu nội bộ / HR data → cite [N], đây là nguồn ưu tiên cao nhất.
2. Nếu tài liệu không đủ → dùng kiến thức chung để giải thích khái niệm/thuật ngữ kỹ thuật
   (vd định nghĩa thuật toán, khái niệm phổ biến). Nêu rõ "theo kiến thức chung" khi dùng.
3. TUYỆT ĐỐI KHÔNG bịa/đoán: số liệu HR cá nhân (ngày phép, lương), chính sách cụ thể
   của công ty → thiếu data phải nói thẳng "không có thông tin", gợi ý liên hệ HR/IT.
- TRÍCH DẪN: DANH SÁCH NGUỒN có số [N]; chèn [N] NGAY SAU ý dùng nguồn đó (vd "...12 ngày [1]").
  TUYỆT ĐỐI KHÔNG viết tên file/đường dẫn trong câu (giao diện tự render thẻ nguồn từ [N]).
  DANH SÁCH NGUỒN trống -> KHÔNG bịa [N].
- Phong cách ấm áp, chuyên nghiệp, vài icon hợp lý (✅ 📌 💡 😊) trừ nội dung nhạy cảm.
"""


def build_orchestrator_graph(
    *,
    ctx: RoleContext,
    manifest: AgentsManifest,
    planner: Planner,
    make_model: Callable[[str], Any] | None,
    checkpointer: Any = None,
):
    role_catalog = manifest.enabled_roles()
    max_per_level = manifest.max_workers_per_level
    worker_timeout = manifest.worker_timeout_seconds

    def _pending_sends(state: OrchestratorState) -> list[Send]:
        plan = state["plan"]
        results = state.get("results") or {}
        done = set(results.keys())
        ready = plan.ready_steps(done)
        sends: list[Send] = []
        # solo: plan chỉ 1 step dữ liệu (đã strip synth/analyze) -> worker bỏ distill thừa
        # (verify_answer synth thẳng trên data thô, tiết kiệm 1 LLM call nối tiếp).
        solo = len(plan.steps) == 1
        for s in ready[:max_per_level]:
            sends.append(Send("worker", {
                "step_id": s.id,
                "role": s.role,
                "input": s.input,
                "direction": s.direction,
                "upstream": upstream_outputs(results, s.depends_on),
                "solo": solo,
            }))
        return sends

    async def orchestrate(state: OrchestratorState) -> dict:
        if ctx.emit:
            await ctx.emit({"phase": "thinking", "node": "orchestrate",
                            "status": "Đang phân tích yêu cầu & lập kế hoạch…"})
        pctx = PlanContext(
            question=state["question"],
            role_catalog=role_catalog,
            make_model=make_model,
            history=state.get("recent_messages"),
            tracer=ctx.tracer, trace=ctx.trace,
            # GỐC RỄ dead-air: thiếu emit -> planner astream_plan fallback acomplete (CÂM) suốt.
            # Nối emit -> planner stream reasoning + prose LIVE lúc lập kế hoạch (lấp dead-air).
            emit=ctx.emit,
            memory=state.get("memory_context"),  # dialogue+summary+task_state -> planner đa lượt
            hint_doc_ids=ctx.hint_doc_ids,
            is_replan=state.get("replan_count", 0) > 0,  # A: replan -> ESCALATE heavy (bỏ fast-path)
        )
        plan = await planner.plan(pctx)
        # synthesize_recommend KHÔNG còn chạy như worker: node `synthesize` tự sinh câu trả lời +
        # gắn [N] citation từ nguồn đã đánh ref (worker chỉ nhận text -> không cite được). Strip
        # step synth khỏi DAG -> workers CHỈ gom dữ liệu (rag/hr/analyze). depends_on của step dữ
        # liệu KHÔNG trỏ vào synth nên bỏ an toàn; route_join chỉ chờ các step dữ liệu.
        # Strip synthesize_recommend + analyze: việc TỔNG HỢP/PHÂN TÍCH/viết dồn vào node
        # verify_answer (1 lần suy luận). Workers CHỈ gom dữ liệu (rag/hr/leave_action).
        if plan.route != "light":
            plan.steps[:] = [s for s in plan.steps if s.role not in (_SYNTH_ROLE, "analyze")]
        logger.info("orchestrate route=%s steps=%d", plan.route, len(plan.steps))
        if ctx.emit:
            # KHÔNG emit lại plan.reasoning (node=think) — astream_plan ĐÃ stream "Lập kế hoạch"
            # (node=plan) live + sạch ngay lúc planner chạy -> tránh khối "Suy nghĩ" trùng lặp.
            # "plan" = cấu trúc node + depends_on -> FE vẽ subagents SONG SONG theo level.
            await ctx.emit({
                "phase": "plan", "route": plan.route,
                "steps": [
                    {"id": s.id, "role": s.role, "direction": s.direction,
                     "depends_on": list(s.depends_on)}
                    for s in plan.steps
                ],
            })
        # GIỮ replan_count (verify tăng lên khi replan) — replan reset results để tra lại từ đầu.
        return {"plan": plan, "replan_count": state.get("replan_count", 0), "results": {}}

    def route_plan(state: OrchestratorState):
        if state["plan"].route == "light":
            return "verify_answer"
        return _pending_sends(state) or "verify_answer"

    async def worker(payload: dict) -> dict:
        task = WorkerInput(
            step_id=payload["step_id"],
            role=payload["role"],
            input=payload.get("input", ""),
            direction=payload.get("direction", ""),
            upstream=payload.get("upstream", {}),
            solo=payload.get("solo", False),
        )
        # Node bắt đầu chạy -> SSE (FE hiện subagent này "đang chạy" trong lane song song).
        if ctx.emit:
            await ctx.emit({"phase": "step", "step_id": task.step_id, "role": task.role,
                            "direction": task.direction, "status": "running"})
        try:
            role_cls = AGENT_REGISTRY.get(task.role)
        except KeyError as exc:
            out = WorkerOutput(task.step_id, task.role, "", status="error", error=str(exc)[:200])
        else:
            role = role_cls(ctx)
            try:
                out = await asyncio.wait_for(role.run(task), timeout=worker_timeout)
            except asyncio.TimeoutError:
                out = WorkerOutput(task.step_id, task.role, "", status="error", error="timeout")
            except Exception as exc:  # noqa: BLE001 — worker lỗi KHÔNG làm vỡ graph
                out = WorkerOutput(task.step_id, task.role, "", status="error", error=str(exc)[:200])
        # Node xong -> SSE (status thật: ok/no_info/error) để FE đánh dấu hoàn tất/lỗi.
        if ctx.emit:
            await ctx.emit({"phase": "step", "step_id": task.step_id, "role": task.role,
                            "status": out.status})
        return {"results": {task.step_id: out}}

    async def join(state: OrchestratorState) -> dict:
        return {}  # barrier; reducer đã merge results

    # verify_before_synthesize: bật/tắt VÒNG REPLAN của verify_answer (thiếu -> tra thêm).
    # False -> verify_answer luôn trả lời thẳng (không <<NEED_MORE>>) = rollback hành vi cũ.
    enable_verify = bool(getattr(manifest, "verify_before_synthesize", False))

    def route_join(state: OrchestratorState):
        plan = state["plan"]
        done = set((state.get("results") or {}).keys())
        if all(s.id in done for s in plan.steps):
            return "verify_answer"
        return _pending_sends(state) or "verify_answer"

    async def verify_answer(state: OrchestratorState) -> dict:
        """GỘP analyze+verify+answer (1 LLM call). Stream reasoning (PANEL node=verify
        "Kiểm tra & tổng hợp") cho user thấy model TỔNG HỢP/PHÂN TÍCH; tự quyết:
        - thiếu + còn hạn mức replan -> "<<NEED_MORE>>" -> orchestrate MỞ RỘNG plan tra thêm.
        - đủ -> STREAM câu trả lời + [N] xuống message.
        Fail-safe: lỗi/không model -> trả dữ liệu thô (không chặn câu trả lời)."""
        plan = state["plan"]
        if plan.route == "light":
            return {"answer": plan.answer_hint or "Mình chưa rõ yêu cầu, bạn nói rõ hơn nhé.",
                    "sources": []}
        results = state.get("results") or {}
        data_results = {k: v for k, v in results.items() if v.role != _SYNTH_ROLE}
        replan_count = state.get("replan_count", 0)

        # ACTION PASSTHROUGH: leave_action xuất PURE JSON action -> trả verbatim (FE.extractAction
        # cần JSON nguyên để render form). KHÔNG qua model, KHÔNG verify.
        for sid in sorted(data_results):
            r = data_results[sid]
            if r.role == _ACTION_ROLE and r.status == "ok" and str(r.output or "").strip():
                return {"answer": str(r.output).strip(), "sources": []}

        # Gom + KHỬ TRÙNG sources, ĐÁNH SỐ ref [1..N] -> prompt trích [N] + done-event cho FE.
        agg: list[dict] = []
        seen: set = set()
        for sid in sorted(data_results):
            for s in (data_results[sid].sources or []):
                cid = s.get("chunk_id") or (s.get("document_name"), s.get("page_number"))
                if cid in seen:
                    continue
                seen.add(cid)
                agg.append(s)
        sources_ref = [{**s, "ref": i + 1} for i, s in enumerate(agg)]
        data_text = _build_data_text(data_results, plan.steps)
        if sources_ref:
            refs_block = "\n".join(
                f"[{s['ref']}] {s.get('document_name', '')}"
                + (f" — {str(s.get('caption', ''))[:140]}" if s.get('caption') else "")
                + (f" (trang {s['page_number']})" if s.get('page_number') else "")
                for s in sources_ref
            )
        else:
            refs_block = "(không có nguồn tài liệu — KHÔNG dùng [N])"

        # RAG MISS TUYỆT ĐỐI (không text, không source) -> KHÔNG gọi synth LLM (vô ích, chỉ để
        # model nói "chưa có thông tin" mất 5-8s). Trả fallback NGAY. Có BẤT KỲ data nào -> bỏ qua
        # nhánh này, để LLM synth bình thường.
        if not data_text.strip() and not sources_ref:
            if ctx.emit:
                await ctx.emit({"phase": "thinking", "node": "verify",
                                "status": "Không tìm được dữ liệu phù hợp."})
            return {"answer": "Mình chưa tìm được thông tin phù hợp. Bạn thử hỏi lại theo "
                              "cách khác hoặc liên hệ HR/IT Helpdesk nhé.", "sources": []}

        # Không có model (mock/test) -> gộp text thô (vẫn trả sources cho FE).
        if make_model is None:
            return {"answer": data_text or
                    "Mình chưa lấy được dữ liệu phù hợp, bạn thử lại hoặc liên hệ HR/IT Helpdesk.",
                    "sources": sources_ref}

        if ctx.emit:
            await ctx.emit({"phase": "thinking", "node": "verify",
                            "status": "Đang tổng hợp & kiểm tra thông tin…"})

        # cho replan khi: bật flag + còn hạn mức + có dữ liệu (để "thiếu" có nghĩa).
        allow_replan = enable_verify and bool(data_results) and replan_count < manifest.max_replan
        from app.agents.roles._llm import astream_verify_answer
        user = (
            f"CÂU HỎI: {state['question']}\n\n"
            f"THÔNG TIN ĐÃ THU THẬP:\n{data_text or '(trống)'}\n\n"
            f"DANH SÁCH NGUỒN (trích bằng số [N]):\n{refs_block}"
        )
        if not allow_replan:
            user += ("\n\n(LƯU Ý: PHẢI trả lời NGAY dù dữ liệu có thể chưa đủ — trung thực phần "
                     "thiếu + gợi ý liên hệ HR/IT. KHÔNG dùng <<NEED_MORE>>.)")
        # 1 call: reasoning -> PANEL node=verify; content -> <<NEED_MORE>> (replan) HOẶC answer stream.
        answer, need_more, missing = await astream_verify_answer(
            make_model("answer"), _VA_SYSTEM, user, ctx.emit, node="verify",
            allow_replan=allow_replan, tracer=ctx.tracer, trace=ctx.trace,
        )
        if need_more:
            logger.info("verify_answer NEED_MORE replan_count=%d missing=%s", replan_count, missing[:80])
            if ctx.emit:
                await ctx.emit({"phase": "thought", "node": "verify",
                                "text": f"Thông tin chưa đủ ({missing or 'thiếu khía cạnh chính'}) — tra cứu thêm."})
            return {"verify_verdict": "insufficient", "replan_count": replan_count + 1}
        if not answer:
            # ⚠️ KHÔNG fallback `data_text` — đó là context THÔ '[rag_retrieve]{results...}' → rò JSON
            # nguyên khối ra message (BUG nghiêm trọng, 6/7 trace huuhung). Model fail/empty -> CHỈ
            # message an toàn cho user (KHÔNG bao giờ dump context).
            answer = "Mình chưa tổng hợp được câu trả lời phù hợp, bạn thử hỏi lại cụ thể hơn hoặc liên hệ HR/IT Helpdesk."
        return {"answer": answer, "sources": sources_ref}

    def route_after(state: OrchestratorState):
        # CHỈ replan khi CHƯA có answer + verdict insufficient (need_more). Có answer -> END NGAY
        # (kể cả verify_verdict cũ còn "insufficient" từ lần replan trước -> tránh lặp vô tận).
        if not state.get("answer") and state.get("verify_verdict") == "insufficient":
            return "orchestrate"
        return END

    g = StateGraph(OrchestratorState)
    g.add_node("orchestrate", orchestrate)
    g.add_node("worker", worker)
    g.add_node("join", join)
    g.add_node("verify_answer", verify_answer)

    g.add_edge(START, "orchestrate")
    g.add_conditional_edges("orchestrate", route_plan, ["worker", "verify_answer"])
    g.add_edge("worker", "join")
    g.add_conditional_edges("join", route_join, ["worker", "verify_answer"])
    g.add_conditional_edges("verify_answer", route_after, ["orchestrate", END])

    compiled = g.compile(checkpointer=checkpointer)
    compiled.name = "VsfOrchestratorWorkers"
    return compiled
