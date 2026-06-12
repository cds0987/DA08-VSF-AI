from app.application.langgraph_state import AgentState
from app.application.shortcuts import classify_shortcut


def route_entry(state: AgentState) -> str:
    """
    Conditional entry point: check shortcuts before triage/LLM call.
    Returns "shortcut" to skip triage, or "triage" to classify before planning.
    Delegates to classify_shortcut() — single source of truth in shortcuts.py.
    """
    if classify_shortcut(state["question"]) is not None:
        return "shortcut"
    return "triage"


def route_after_triage(state: AgentState) -> str:
    """
    Conditional edge after triage_node.
    - triage decided refuse/clarify/safety/meta? → answer_node (shortcut_outcome is set)
    - triage decided allow?                      → plan_node (build tool execution plan)
    """
    if state.get("shortcut_outcome"):
        return "answer"
    return "plan"


def route_after_plan(state: AgentState) -> str:
    """
    Conditional edge after plan_node.
    - Empty plan (direct_answer or no steps produced) → answer_node immediately
    - Non-empty plan                                  → act_node (execute first step)
    """
    plan = state.get("tool_plan") or []
    if not plan:
        return "answer"
    return "act"


def route_after_observe(state: AgentState) -> str:
    """
    Conditional edge after observe_node.
    - plan_cursor < len(tool_plan): more steps to execute → act_node
    - plan_cursor >= len(tool_plan): all steps done      → think_node (check sufficiency)

    Safety: if iteration cap is hit, also go to think (which will mark enough=True
    as fail-safe and route directly to answer).
    """
    plan = state.get("tool_plan") or []
    cursor = state.get("plan_cursor", 0)
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 3)

    if iteration >= max_iterations:
        # Hard cap reached — skip remaining plan steps, go straight to think
        return "think"
    if cursor < len(plan):
        return "act"
    return "think"


def route_after_think(state: AgentState) -> str:
    """
    Conditional edge after think_node (sufficiency check).
    - enough=True OR replan budget exhausted (replan_count >= 1) → answer_node
    - enough=False AND replan_count < 1                           → plan_node (replan)
    """
    sufficiency = state.get("sufficiency") or {}
    enough = sufficiency.get("enough", True)   # default True = safe fail-open
    replan_count = state.get("replan_count", 0)

    if enough or replan_count >= 1:
        return "answer"
    return "plan"
