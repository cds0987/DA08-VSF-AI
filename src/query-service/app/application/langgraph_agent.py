"""
LangGraph agent compiler for VinSmartFuture.

Factory function that builds and compiles the Plan-and-Execute graph with a
triage node and a plan node.

Graph topology:
  START
    → route_entry
      → "shortcut" → shortcut_node → answer_node(canned) → END
      → "triage"   → triage_node
                      → route_after_triage
                        → "answer" (refuse/clarify/safety/meta, canned) → END
                        → "plan"   (allow)
                            → plan_node   [structured output — silent]
                              → route_after_plan
                                → "answer" (direct_answer / empty steps)  → END
                                → "act"
                                    → act_node → observe_node
                                                  → route_after_observe
                                                       → "act"   (more plan steps)
                                                       → "think" (all steps done)
                                                           → think_node  [structured — silent]
                                                             → route_after_think
                                                                  → "answer" (enough / replan budget exhausted)
                                                                  → "plan"   (replan, max 1 time)
                        → "answer" → answer_node(streaming synthesis) → END
"""

from functools import partial
from langgraph.graph import StateGraph, START, END

from app.application.langgraph_state import AgentState
from app.application.langgraph_edges import (
    route_entry,
    route_after_triage,
    route_after_plan,
    route_after_observe,
    route_after_think,
)
from app.application.langgraph_nodes import (
    shortcut_node,
    triage_node,
    plan_node,
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
    Build and compile the LangGraph Plan-and-Execute agent with triage + plan nodes.

    Args:
        model: LangChain-compatible chat model (OpenAIResponsesChatModel).
               Used for: triage (prompt-JSON), plan (with_structured_output),
               think (with_structured_output), answer (streaming ainvoke).
        mcp_client: MCP tool client for rag_search and hr_query (used by act_node).
        tools_loader: retained for API compat; not used in plan architecture
                      (plan_node uses ToolPlan schema instead of dynamic tool list).
        checkpointer: Optional LangGraph checkpointer for multi-turn conversations.

    Returns:
        A compiled LangGraph that can be invoked or streamed.
    """
    workflow = StateGraph(AgentState)

    # ---- Nodes ----
    workflow.add_node("shortcut", shortcut_node)
    workflow.add_node("triage", partial(triage_node, model=model))
    workflow.add_node("plan", partial(plan_node, model=model))
    workflow.add_node("think", partial(think_node, model=model))
    workflow.add_node("act", partial(act_node, mcp_client=mcp_client))
    workflow.add_node("observe", observe_node)
    workflow.add_node("answer", partial(answer_node, model=model))

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
    # triage_node → answer_node (refuse/clarify/safety/meta) or plan_node (allow)
    workflow.add_conditional_edges(
        source="triage",
        path=route_after_triage,
        path_map={
            "answer": "answer",
            "plan": "plan",
        },
    )

    # plan_node → answer_node (direct / empty plan) or act_node (execute first step)
    workflow.add_conditional_edges(
        source="plan",
        path=route_after_plan,
        path_map={
            "answer": "answer",
            "act": "act",
        },
    )

    # act_node → observe_node (always; observe decides next step via routing)
    workflow.add_edge("act", "observe")

    # observe_node → act_node (more plan steps) or think_node (all steps done)
    workflow.add_conditional_edges(
        source="observe",
        path=route_after_observe,
        path_map={
            "act": "act",
            "think": "think",
        },
    )

    # think_node → answer_node (enough / budget exhausted) or plan_node (replan)
    workflow.add_conditional_edges(
        source="think",
        path=route_after_think,
        path_map={
            "answer": "answer",
            "plan": "plan",
        },
    )

    # Terminal edges
    workflow.add_edge("shortcut", "answer")
    workflow.add_edge("answer", END)

    # ---- Compile ----
    compiled = workflow.compile(checkpointer=checkpointer)
    compiled.name = "VinSmartFutureAgent"

    return compiled
