"""Build LangGraph cho mode=orchestrator_workers (fan-out động theo DAG).

Graph: START -> orchestrate -> (light? synthesize : dispatch Send[worker]) ;
worker -> join -> (còn step? dispatch : synthesize) -> END.

Node functions CLOSURE quanh ctx/make_model (mcp_client KHÔNG đi vào state -> an toàn
checkpointer). Send payload chỉ mang dữ liệu step (serializable).
"""
from __future__ import annotations

import asyncio
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
        return {"plan": plan, "replan_count": 0, "results": {}}

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

    def route_join(state: OrchestratorState):
        plan = state["plan"]
        done = set((state.get("results") or {}).keys())
        if all(s.id in done for s in plan.steps):
            return "synthesize"
        return _pending_sends(state) or "synthesize"

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
    g.add_node("synthesize", synthesize)

    g.add_edge(START, "orchestrate")
    g.add_conditional_edges("orchestrate", route_plan, ["worker", "synthesize"])
    g.add_edge("worker", "join")
    g.add_conditional_edges("join", route_join, ["worker", "synthesize"])
    g.add_edge("synthesize", END)

    compiled = g.compile(checkpointer=checkpointer)
    compiled.name = "VsfOrchestratorWorkers"
    return compiled
