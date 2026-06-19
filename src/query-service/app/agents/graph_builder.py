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
        )
        plan = await planner.plan(pctx)
        logger.info("orchestrate route=%s steps=%d", plan.route, len(plan.steps))
        if ctx.emit:
            # "Suy nghĩ" = router NGHĨ GÌ (reasoning thật); thiếu -> fallback ngắn theo route.
            _think = plan.reasoning.strip() if plan.reasoning else (
                "Trả lời trực tiếp." if plan.route == "light"
                else "Cần truy xuất dữ liệu rồi tổng hợp."
            )
            await ctx.emit({"phase": "thought", "node": "think", "text": _think})
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

        # Không có dữ liệu / hết hạn mức replan / không có model -> đi synthesize luôn.
        if not data_results or replan_count >= manifest.max_replan or make_model is None:
            return {"verify_verdict": "sufficient"}

        if ctx.emit:
            await ctx.emit({"phase": "thinking", "node": "verify",
                            "status": "Đang tổng hợp & kiểm tra thông tin đã đủ chưa…"})

        evidence = "\n\n".join(
            f"[step {k}] {v.output}" for k, v in sorted(data_results.items())
        )
        from app.agents.roles._llm import acomplete
        # capability "think" = deepseek-pro qua ai-router (đúng yêu cầu "deepseek pro tổng hợp lại").
        _model = make_model("think")
        _user = f"Câu hỏi: {state['question']}\n\nDữ liệu thu thập:\n{evidence}"
        # STREAM reasoning live ra SSE (phase=thought, node=verify) -> FE hiện "Kiểm tra & tổng
        # hợp" chạy dần, user thấy model đang làm gì (không "im lặng"). content (JSON verdict) gom
        # để parse. Model không hỗ trợ astream / lỗi -> fallback acomplete (non-stream).
        text: str | None = None
        if ctx.emit and _model is not None and hasattr(_model, "astream"):
            try:
                from langchain_core.messages import HumanMessage, SystemMessage
                _parts: list[str] = []
                async for _chunk in _model.astream(
                    [SystemMessage(content=_VERIFY_SYSTEM), HumanMessage(content=_user)]
                ):
                    _rc = (getattr(_chunk, "additional_kwargs", None) or {}).get("reasoning_content")
                    if _rc:
                        await ctx.emit({"phase": "thought", "node": "verify", "text": _rc})
                    _tok = getattr(_chunk, "content", "") or ""
                    if _tok:
                        _parts.append(_tok)
                text = "".join(_parts).strip() or None
            except Exception as exc:  # noqa: BLE001 — stream lỗi -> non-stream
                logger.warning("verify stream fail -> acomplete: %s", str(exc)[:120])
                text = None
        if text is None:
            text = await acomplete(_model, system=_VERIFY_SYSTEM, user=_user)
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
        synth_ids = [sid for sid, o in results.items() if o.role == _SYNTH_ROLE]
        data_results = {k: v for k, v in results.items() if v.role != _SYNTH_ROLE}
        if synth_ids:
            answer = results[max(synth_ids)].output
        else:
            # Plan không có synthesize step -> gộp output dữ liệu (fallback hiếm).
            answer = "\n\n".join(str(results[k].output) for k in sorted(data_results)) or \
                "Mình chưa lấy được dữ liệu phù hợp, bạn thử lại hoặc liên hệ HR/IT Helpdesk."
        return {"answer": answer, "sources": aggregate_sources(data_results)}

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
