from app.application.langgraph_state import AgentState
from app.application.shortcuts import classify_shortcut


def route_entry(state: AgentState) -> str:
    """
    Conditional entry point: check shortcuts before triage/LLM call.
    Returns "shortcut" to skip triage, or "triage" to classify before calling tools.
    Delegates to classify_shortcut() — single source of truth in shortcuts.py.
    """
    if classify_shortcut(state["question"]) is not None:
        return "shortcut"
    return "triage"


def route_after_triage(state: AgentState) -> str:
    """
    Conditional edge after triage_node.
    - triage decided off_topic/clarify? → answer_node (shortcut_outcome is set)
    - triage decided in_scope?          → think_node (call MCP tools)
    """
    if state.get("shortcut_outcome"):
        return "answer"
    return "think"


def route_after_think(state: AgentState) -> str:
    """
    Conditional edge after think_node.
    - Has tool_calls? → act_node
    - No tool_calls? → answer_node (final answer)
    """
    messages = state.get("messages") or []
    if not messages:
        return "answer"
    last_msg = messages[-1]
    tool_calls = getattr(last_msg, "tool_calls", None) or []
    if tool_calls:
        return "act"
    return "answer"


def route_after_act(state: AgentState) -> str:
    """
    Conditional edge after act_node.

    Hard-stop (shortcut_outcome set) only for technical errors:
    ACL violation (no doc access), MCP circuit open, or uncaught exception.
    Empty results without error fall through to observe → think → LLM.
    """
    if state.get("shortcut_outcome"):
        return "answer"
    return "observe"


