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
    last_msg = state["messages"][-1]
    tool_calls = getattr(last_msg, "tool_calls", None) or []
    if tool_calls:
        return "act"
    return "answer"


def route_after_act(state: AgentState) -> str:
    """
    Conditional edge after act_node.

    rag_search may decide the request must end with a hard NO_INFO response
    (for example no document access or no qualified sources). In that case,
    do not loop back into the LLM.
    """
    if state.get("shortcut_outcome"):
        return "answer"
    return "observe"


def route_after_observe(state: AgentState) -> str:
    """
    After observing tool result, always go back to think_node.
    (think_node uses state["force_answer"] to decide whether to call tools or emit the final answer.)
    """
    return "think"
