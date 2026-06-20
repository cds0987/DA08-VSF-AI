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
        for s in ready[:max_per_level]:
            sends.append(Send("worker", {
                "step_id": s.id,
                "role": s.role,
                "input": s.input,
                "direction": s.direction,
                "upstream": upstream_outputs(results, s.depends_on),
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
        )
        plan = await planner.plan(pctx)
        # synthesize_recommend KHÔNG còn chạy như worker: node `synthesize` tự sinh câu trả lời +
        # gắn [N] citation từ nguồn đã đánh ref (worker chỉ nhận text -> không cite được). Strip
        # step synth khỏi DAG -> workers CHỈ gom dữ liệu (rag/hr/analyze). depends_on của step dữ
        # liệu KHÔNG trỏ vào synth nên bỏ an toàn; route_join chỉ chờ các step dữ liệu.
        if plan.route != "light":
            plan.steps[:] = [s for s in plan.steps if s.role != _SYNTH_ROLE]
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
            return "synthesize"
        return _pending_sends(state) or "synthesize"

    async def worker(payload: dict) -> dict:
        task = WorkerInput(
            step_id=payload["step_id"],
            role=payload["role"],
            input=payload.get("input", ""),
            direction=payload.get("direction", ""),
            upstream=payload.get("upstream", {}),
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

    enable_verify = bool(getattr(manifest, "verify_before_synthesize", False))
    # Đích khi mọi step xong: verify (think 2) nếu bật, ngược lại synthesize thẳng.
    _all_done_target = "verify" if enable_verify else "synthesize"

    def route_join(state: OrchestratorState):
        plan = state["plan"]
        done = set((state.get("results") or {}).keys())
        if all(s.id in done for s in plan.steps):
            return _all_done_target
        return _pending_sends(state) or _all_done_target

    async def verify(state: OrchestratorState) -> dict:
        """think 2: deepseek-pro TỔNG HỢP lại dữ liệu đã thu thập + quyết ĐỦ chưa.
        Đủ -> synthesize; thiếu (còn hạn mức replan) -> orchestrate lại để tra thêm.
        Fail-open: lỗi/parse hỏng/hết hạn mức -> coi là đủ (không chặn câu trả lời)."""
        results = state.get("results") or {}
        data_results = {k: v for k, v in results.items() if v.role != _SYNTH_ROLE}
        replan_count = state.get("replan_count", 0)

        # leave_action xuất action JSON / câu hỏi làm rõ -> KHÔNG verify "đủ thông tin" (vô nghĩa,
        # và replan sẽ tạo lại đơn). Đi thẳng synthesize (passthrough).
        if any(v.role == _ACTION_ROLE for v in data_results.values()):
            return {"verify_verdict": "sufficient"}

        # Không có dữ liệu / hết hạn mức replan / không có model -> đi synthesize luôn.
        if not data_results or replan_count >= manifest.max_replan or make_model is None:
            return {"verify_verdict": "sufficient"}

        if ctx.emit:
            await ctx.emit({"phase": "thinking", "node": "verify",
                            "status": "Đang kiểm tra thông tin đã đủ chưa…"})

        evidence = "\n\n".join(
            f"[step {k}] {v.output}" for k, v in sorted(data_results.items())
        )
        from app.agents.roles._llm import acomplete
        # think 2 = TỔNG HỢP + VERIFY -> capability "synth" RIÊNG (đổi model chỉ sửa routing.yaml).
        # KHÔNG stream raw CoT của verify (trước đây dump cả tính toán BHXH "Tuy nhiên/Hoặc là" ->
        # rối). Chỉ hiện status "Đang kiểm tra & tổng hợp…" (đã emit ở trên). acomplete gom verdict.
        _model = make_model("synth")
        _user = f"Câu hỏi: {state['question']}\n\nDữ liệu thu thập:\n{evidence}"
        text = await acomplete(_model, _VERIFY_SYSTEM, _user,
                               tracer=ctx.tracer, trace=ctx.trace, node="verify")
        verdict = "sufficient"
        reason = ""
        if text:
            try:
                s, e = text.find("{"), text.rfind("}")
                data = json.loads(text[s:e + 1])
                verdict = "insufficient" if not bool(data.get("sufficient", True)) else "sufficient"
                reason = str(data.get("reason", ""))[:200]
            except Exception as exc:  # noqa: BLE001 — fail-open
                logger.warning("verify parse fail -> sufficient: %s", str(exc)[:120])
        logger.info("verify verdict=%s replan_count=%d reason=%s", verdict, replan_count, reason[:80])

        if verdict == "insufficient":
            if ctx.emit:
                await ctx.emit({"phase": "thought", "node": "verify",
                                "text": f"Thông tin chưa đủ ({reason or 'thiếu khía cạnh chính'}) — tra cứu thêm."})
            return {"verify_verdict": "insufficient", "replan_count": replan_count + 1}
        return {"verify_verdict": "sufficient"}

    def route_after_verify(state: OrchestratorState):
        # insufficient -> orchestrate lại (tra thêm); còn lại -> synthesize.
        return "orchestrate" if state.get("verify_verdict") == "insufficient" else "synthesize"

    async def synthesize(state: OrchestratorState) -> dict:
        plan = state["plan"]
        if plan.route == "light":
            return {"answer": plan.answer_hint or "Mình chưa rõ yêu cầu, bạn nói rõ hơn nhé.",
                    "sources": []}
        results = state.get("results") or {}
        data_results = {k: v for k, v in results.items() if v.role != _SYNTH_ROLE}

        # ACTION PASSTHROUGH: leave_action xuất PURE JSON action (create_leave_request /
        # review_leave_approvals) hoặc câu hỏi làm rõ. TUYỆT ĐỐI KHÔNG rewrite qua model (sẽ phá
        # JSON mà FE.extractAction cần để render form xác nhận). Trả verbatim + sources rỗng.
        # KHÔNG emit token ở đây -> streamed_tokens=False -> orchestration word-chunk câu trả lời
        # (FE gom fullContent rồi tách action JSON). Lấy step leave_action ĐẦU TIÊN có output.
        for sid in sorted(data_results):
            r = data_results[sid]
            if r.role == _ACTION_ROLE and r.status == "ok" and str(r.output or "").strip():
                return {"answer": str(r.output).strip(), "sources": []}

        # Gom + KHỬ TRÙNG sources theo chunk_id, ĐÁNH SỐ ref [1..N] (theo thứ tự step). Ref này
        # vừa đưa vào prompt cho model trích [N], vừa trả ra done-event cho FE -> [N] khớp thẻ nguồn.
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

        # Text dữ liệu các worker (rag/hr/analyze) — đầu vào để model viết câu trả lời.
        data_text = "\n\n".join(
            f"[{data_results[k].role}] {data_results[k].output}"
            for k in sorted(data_results)
            if str(data_results[k].output or "").strip()
        )
        if sources_ref:
            refs_block = "\n".join(
                f"[{s['ref']}] {s.get('document_name', '')}"
                + (f" — {str(s.get('caption', ''))[:140]}" if s.get('caption') else "")
                + (f" (trang {s['page_number']})" if s.get('page_number') else "")
                for s in sources_ref
            )
        else:
            refs_block = "(không có nguồn tài liệu — KHÔNG dùng [N])"

        # Không có model (mock/test) -> gộp text thô (vẫn trả sources cho FE).
        if make_model is None:
            return {"answer": data_text or
                    "Mình chưa lấy được dữ liệu phù hợp, bạn thử lại hoặc liên hệ HR/IT Helpdesk.",
                    "sources": sources_ref}

        if ctx.emit:
            await ctx.emit({"phase": "thinking", "node": "answer",
                            "status": "Đang soạn câu trả lời..."})
        from app.agents.roles._llm import astream_complete
        user = (
            f"CÂU HỎI: {state['question']}\n\n"
            f"THÔNG TIN ĐÃ THU THẬP:\n{data_text or '(trống)'}\n\n"
            f"DANH SÁCH NGUỒN (trích bằng số [N]):\n{refs_block}"
        )
        # STREAM token answer ra SSE (node=answer) + surface reasoning. capability "answer".
        answer = await astream_complete(make_model("answer"), _SYNTH_CITE_SYSTEM, user,
                                        ctx.emit, node="answer",
                                        tracer=ctx.tracer, trace=ctx.trace)
        if not answer:
            answer = data_text or \
                "Mình chưa lấy được dữ liệu phù hợp, bạn thử lại hoặc liên hệ HR/IT Helpdesk."
        return {"answer": answer, "sources": sources_ref}

    g = StateGraph(OrchestratorState)
    g.add_node("orchestrate", orchestrate)
    g.add_node("worker", worker)
    g.add_node("join", join)
    if enable_verify:
        g.add_node("verify", verify)
    g.add_node("synthesize", synthesize)

    g.add_edge(START, "orchestrate")
    g.add_conditional_edges("orchestrate", route_plan, ["worker", "synthesize"])
    g.add_edge("worker", "join")
    if enable_verify:
        g.add_conditional_edges("join", route_join, ["worker", "verify", "synthesize"])
        # verify (think 2): đủ -> synthesize; thiếu -> orchestrate lại (replan trong max_replan).
        g.add_conditional_edges("verify", route_after_verify, ["orchestrate", "synthesize"])
    else:
        g.add_conditional_edges("join", route_join, ["worker", "synthesize"])
    g.add_edge("synthesize", END)

    compiled = g.compile(checkpointer=checkpointer)
    compiled.name = "VsfOrchestratorWorkers"
    return compiled
