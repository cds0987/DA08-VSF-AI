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
    model: BaseChatModel | None = None,
    mcp_client: MCPToolClient = None,
    tools_loader=None,
    checkpointer=None,
    *,
    models: dict[str, BaseChatModel] | None = None,
    split_answer: bool = False,
) -> "CompiledGraph":
    """
    Build and compile the LangGraph agent with triage + ReAct loop.

    Model wiring (MOSA per-node):
        - models={"triage":.., "think":.., "answer":..}: mỗi node 1 model riêng.
        - model=<1 model>: dùng chung cho mọi node (back-compat path 'responses').
    split_answer=True: answer_node gọi `models["answer"]` để SINH câu trả lời (stream),
        tách khỏi think (planner/reasoning). False: answer_node là marker (think tự sinh).

    Args:
        model: 1 model dùng chung (khi không truyền `models`).
        mcp_client: MCP tool client for rag_search and hr_query (act_node + fallback).
        tools_loader: optional LangChainMCPToolsLoader.
        models: dict model theo node (ưu tiên hơn `model`).
        split_answer: bật answer node sinh-chữ-riêng.
    """
    _m = models or {}
    triage_model = _m.get("triage") or model
    think_model = _m.get("think") or model
    answer_model = _m.get("answer") or model

    workflow = StateGraph(AgentState)

    # ---- Nodes ----
    workflow.add_node("shortcut", shortcut_node)
    workflow.add_node("triage", partial(triage_node, model=triage_model))
    workflow.add_node(
        "think",
        partial(think_node, model=think_model, mcp_client=mcp_client, tools_loader=tools_loader),
    )
    workflow.add_node("act", partial(act_node, mcp_client=mcp_client))
    workflow.add_node("observe", observe_node)
    # answer: split=True -> gọi answer_model sinh câu trả lời; False -> marker (think tự sinh).
    workflow.add_node(
        "answer",
        partial(answer_node, model=answer_model if split_answer else None, split=split_answer),
    )

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

    # act_node → observe_node (always); observe_node → think_node (always loop back).
    # The iteration cap + force_answer flag (set in observe_node / act_node) cause
    # think_node to produce a final text answer, which route_after_think routes to answer.
    workflow.add_conditional_edges(
        source="act",
        path=route_after_act,
        path_map={
            "answer": "answer",
            "observe": "observe",
        },
    )
    workflow.add_edge("observe", "think")

    # Terminal edges
    workflow.add_edge("shortcut", "answer")
    workflow.add_edge("answer", END)

    # ---- Compile ----
    compiled = workflow.compile(checkpointer=checkpointer)
    compiled.name = "VinSmartFutureAgent"

    return compiled
