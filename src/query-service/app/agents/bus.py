"""Communication bus — shared blackboard cho Orchestrator-Workers.

Vấn đề: N worker chạy SONG SONG (LangGraph Send API) cùng ghi vào state.results.
LangGraph gọi reducer để hợp các bản cập nhật đồng thời -> KHÔNG được clobber.
Mỗi worker return {"results": {step_id: WorkerOutput}}; reducer merge theo step_id.

State Orchestrator-Workers tách khỏi AgentState (react cũ) để không đụng flow prod;
graph_builder (milestone 6) compose khi mode=orchestrator_workers.
"""
from __future__ import annotations

from typing import Annotated, Any, TypedDict

from app.agents.base import WorkerOutput
from app.agents.plan_schema import Plan


def merge_step_results(
    existing: dict[int, WorkerOutput] | None,
    new: dict[int, WorkerOutput] | None,
) -> dict[int, WorkerOutput]:
    """Reducer: hợp 2 dict kết quả theo step_id (immutable, không sửa input).

    Worker song song mỗi cái ghi step_id KHÁC nhau -> union không xung đột.
    Nếu trùng step_id (vd replan/retry) -> bản MỚI ghi đè bản cũ (last-write-wins).
    """
    merged: dict[int, WorkerOutput] = dict(existing or {})
    merged.update(new or {})
    return merged


class OrchestratorState(TypedDict, total=False):
    """State cho graph orchestrator_workers. total=False: field điền dần qua các node."""

    # --- Input (inject tại entry, LLM không sửa) ---
    session_id: str
    question: str
    user_id: str
    user_role: str
    user_department: str
    allowed_doc_ids: list[str]
    rag_top_k: int
    rag_score_threshold: float
    recent_messages: list  # memory provider nạp (milestone 7)
    memory_context: Any    # MemoryContext (dialogue+summary+task_state+working_set) -> PlanContext

    # --- Plan do orchestrator/router sinh ---
    plan: Plan

    # --- Blackboard: kết quả worker, merge song song qua reducer ---
    results: Annotated[dict[int, WorkerOutput], merge_step_results]

    # --- Scheduler bookkeeping ---
    replan_count: int
    # verify_verdict: "sufficient" | "insufficient" do verify node (think 2) đặt -> route
    # quyết đi synthesize hay replan. Rỗng = chưa qua verify.
    verify_verdict: str

    # --- Output ---
    answer: str
    sources: list[dict[str, Any]]


def aggregate_sources(results: dict[int, WorkerOutput]) -> list[dict[str, Any]]:
    """Gom sources từ mọi worker (theo thứ tự step_id) cho synthesize/citation."""
    out: list[dict[str, Any]] = []
    for step_id in sorted(results):
        out.extend(results[step_id].sources)
    return out


def upstream_outputs(results: dict[int, WorkerOutput], depends_on: list[int]) -> dict[int, Any]:
    """Trích output các step phụ thuộc -> đưa vào WorkerInput.upstream."""
    return {dep: results[dep].output for dep in depends_on if dep in results}
