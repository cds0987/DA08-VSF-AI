"""
LangGraph agent compiler for VinSmartFuture.

Factory function that builds and compiles the ReAct graph with a triage node.
This is the single function called by FastAPI dependency injection.

Graph topology:
  START
    → route_entry
      → "shortcut" → shortcut_node → answer_node → END
      → "triage"   → triage_node
                      → route_after_triage
                        → "answer" (off_topic/clarify) → answer_node → END
                        → "think"  (in_scope)
                            → route_after_think
                              → "act" → act_node → route_after_act → ...
                              → "answer" → answer_node → END
"""

from functools import partial
from langgraph.graph import StateGraph, START, END

from app.application.langgraph_state import AgentState
from app.application.langgraph_edges import (
    route_entry,
    route_after_triage,
    route_after_think,
    route_after_act,
)
from app.application.langgraph_nodes import (
    shortcut_node,
    triage_node,
    think_node,
    act_node,
    observe_node,
    answer_node,
)
from app.application.ports import MCPToolClient
from langchain_core.language_models import BaseChatModel


def build_langgraph_agent(
    model: BaseChatModel,
    mcp_client: MCPToolClient,
    tools_loader=None,
    checkpointer=None,
) -> "CompiledGraph":
    """
    Build and compile the LangGraph agent with triage + ReAct loop.

    Args:
        model: LangChain-compatible chat model (e.g. OpenAIResponsesChatModel)
        mcp_client: MCP tool client for rag_search and hr_query (used by act_node
            and as fallback when tools_loader is None)
        tools_loader: optional LangChainMCPToolsLoader; when provided, think_node
            uses auto-discovered MCP tool descriptions instead of hardcoded schemas
        checkpointer: Optional LangGraph checkpointer for multi-turn conversations

    Returns:
        A compiled LangGraph that can be invoked or streamed.
    """
    workflow = StateGraph(AgentState)

    # ---- Nodes ----
    workflow.add_node("shortcut", shortcut_node)
    workflow.add_node("triage", partial(triage_node, model=model))
    workflow.add_node(
        "think",
        partial(think_node, model=model, mcp_client=mcp_client, tools_loader=tools_loader),
    )
    workflow.add_node("act", partial(act_node, mcp_client=mcp_client))
    workflow.add_node("observe", observe_node)
    workflow.add_node("answer", answer_node)

    # ---- Entry point ----
    # Conditional entry: check shortcuts before triage/LLM
    workflow.set_conditional_entry_point(
        route_entry,
        path_map={
            "shortcut": "shortcut",
            "triage": "triage",
        },
    )

    # ---- Edges ----
    # triage_node → answer_node (off_topic/clarify) or think_node (in_scope)
    workflow.add_conditional_edges(
        source="triage",
        path=route_after_triage,
        path_map={
            "answer": "answer",
            "think": "think",
        },
    )

    # think_node → act_node (tool call) or answer_node (final answer)
    workflow.add_conditional_edges(
        source="think",
        path=route_after_think,
        path_map={
            "act": "act",
            "answer": "answer",
        },
    )

    # act_node → think_node (loop) or answer_node (max iterations)
    workflow.add_conditional_edges(
        source="act",
        path=route_after_act,
        path_map={
            "think": "think",
            "answer": "answer",
        },
    )

    # observe_node → think_node (always loop back)
    workflow.add_edge("observe", "think")

    # Terminal edges
    workflow.add_edge("shortcut", "answer")
    workflow.add_edge("answer", END)

    # ---- Compile ----
    compiled = workflow.compile(checkpointer=checkpointer)
    compiled.name = "VinSmartFutureAgent"

    return compiled
