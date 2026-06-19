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
                              → "act" → act_node → route_after_act → observe → ...
                              → "answer" → answer_node → END

  Khi verify_sufficiency=True (kèm split_answer): observe → verify_node → route_after_verify
    → "think"  (thiếu thông tin → tra cứu thêm, trong max_iterations)
    → "answer" (đủ → synthesis). Khi tắt: observe → think (như cũ).
"""

from functools import partial
from langgraph.graph import StateGraph, START, END

from app.application.langgraph_state import AgentState
from app.application.langgraph_edges import (
    route_entry,
    route_after_triage,
    route_after_think,
    route_after_act,
    route_after_verify,
)
from app.application.langgraph_nodes import (
    shortcut_node,
    triage_node,
    think_node,
    act_node,
    observe_node,
    verify_node,
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
    merged_reason: bool = False,
    verify_sufficiency: bool = False,
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
    # verify (sufficiency gate "think 2") mặc định DÙNG model think (deepseek-pro) — đúng yêu cầu
    # "deepseek pro tổng hợp lại"; cho phép override qua models["verify"] nếu cần.
    verify_model = _m.get("verify") or think_model

    # verify_node chỉ có nghĩa khi answer node thực sự SYNTHESIZE (split_answer). Khi split=False
    # answer là marker (think tự sinh text), gate verify->answer sẽ không có câu trả lời -> tắt.
    enable_verify = bool(verify_sufficiency and split_answer)

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
    if enable_verify:
        workflow.add_node("verify", partial(verify_node, model=verify_model))
    # answer: split=True -> gọi answer_model sinh câu trả lời; False -> marker (think tự sinh).
    workflow.add_node(
        "answer",
        partial(answer_node, model=answer_model if split_answer else None, split=split_answer),
    )

    # ---- Entry point ----
    # Conditional entry: check shortcuts before triage/LLM
    # merged_reason: GỘP triage vào think — route_entry vẫn trả "triage" nhưng map THẲNG
    # sang think (bỏ 1 LLM call triage). think tự phân loại (xem _CLASSIFY_GUIDANCE) + tool.
    # SAFETY/identity vẫn do shortcut (rule) giữ. False = giữ triage riêng (hành vi cũ).
    workflow.set_conditional_entry_point(
        route_entry,
        path_map={
            "shortcut": "shortcut",
            "triage": "think" if merged_reason else "triage",
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
    # observe → verify (sufficiency gate) → think (tra thêm) / answer (synthesis), HOẶC
    # observe → think trực tiếp (hành vi cũ khi verify tắt).
    if enable_verify:
        workflow.add_edge("observe", "verify")
        workflow.add_conditional_edges(
            source="verify",
            path=route_after_verify,
            path_map={
                "think": "think",
                "answer": "answer",
            },
        )
    else:
        workflow.add_edge("observe", "think")

    # Terminal edges
    workflow.add_edge("shortcut", "answer")
    workflow.add_edge("answer", END)

    # ---- Compile ----
    compiled = workflow.compile(checkpointer=checkpointer)
    compiled.name = "VinSmartFutureAgent"

    return compiled
