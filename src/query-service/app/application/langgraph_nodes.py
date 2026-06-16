"""
LangGraph node implementations for the VinSmartFuture ReAct agent.

Architecture:
  shortcut_node  - Fast-path for identity/clarify/security/off-topic (no LLM call)
  think_node     - LLM decides action via structured tool_calls
  act_node       - Execute tool with ACL guard
  observe_node   - Log state + increment iteration counter
  answer_node    - Stream final answer
"""

import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool

from app.application.langgraph_state import (
    AgentState,
    AgentPhase,
    ToolCallResult,
    SourceDoc,
)
from app.application.ports import MCPToolClient
from app.infrastructure.external.mcp_client import MCPCircuitOpenError
from app.application.shortcuts import (
    classify_shortcut,
    IDENTITY_ANSWER,
    CLARIFY_ANSWER,
    SECURITY_ANSWER,
    OFFTOPIC_ANSWER,
    EMERGENCY_ANSWER,
    DISTRESS_ANSWER,
    INJURY_ANSWER,
    USER_PROFILE_PLACEHOLDER,
    next_offtopic_answer,
    IDENTITY_PHRASES,
    CLARIFY_PHRASES,
    SECURITY_PHRASES,
    OFFTOPIC_PHRASES,
    normalize as _normalize,
)
from app.application.tools import TOOL_DEFINITIONS, ACL_WHITELIST
from app.application.prompts import TRIAGE_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool wrappers (LangGraph-compatible, with ACL guard embedded)
# ---------------------------------------------------------------------------

async def build_langgraph_tools(
    mcp_client: MCPToolClient,
    allowed_doc_ids: frozenset[str],
    user_id: str,
) -> list[BaseTool]:
    """
    Build LangGraph-compatible tool wrappers around the MCP client.
    ACL guard is embedded: allowed_doc_ids and user_id come from auth,
    not from LLM arguments.
    """
    from langchain_core.tools import tool

    @tool
    async def rag_search(top_k: int = 5) -> str:
        """
        Search internal company documents, policies, and procedures.

        The user's question is automatically used as the search query — do NOT pass a query
        parameter.  Just call this tool; act_node injects the raw question server-side (same
        pattern as user_id / document_ids).

        Args:
            top_k: Number of results to return (default 5, max 5).
        """
        # Schema-only stub: act_node is the sole execution point for rag_search.
        # It calls mcp_client.rag_search(query=state["question"], ...) directly,
        # so this coroutine is never invoked at runtime.
        _ = (mcp_client, allowed_doc_ids, top_k)  # suppress unused-variable warnings
        return json.dumps({"results": []})

    @tool
    async def hr_query() -> str:
        """
        Lấy TOÀN BỘ hồ sơ HR cá nhân của user hiện tại (chỉ đọc, tự lọc theo user_id).
        KHÔNG cần tham số — trả về: số phép còn lại, lịch sử đơn nghỉ, chấm công,
        tiến độ onboarding, bảng lương, phúc lợi, đánh giá hiệu suất.
        Dùng cho MỌI câu hỏi HR cá nhân (lương/phép/chấm công/phúc lợi/đánh giá/onboarding).
        Đừng dùng cho câu hỏi chính sách chung — dùng rag_search.
        """
        # Stub schema: act_node là điểm thực thi duy nhất (gọi profile + trả full data).
        _ = (mcp_client, user_id)
        return "{}"

    # hr_query KHÔNG tham số -> model gọi hr_query() (rỗng = HỢP LỆ) -> hết failure mode
    # "intent rỗng". act_node lấy full profile từ mcp (user_id tiêm server-side), LLM tự
    # nhặt phần liên quan. rag_search giữ bespoke (ACL/score/sources).
    tools: list = [rag_search, hr_query]

    # Tool KHÁC (ngoài rag_search/hr_query): vẫn discover ĐỘNG từ mcp -> dict schema.
    try:
        specs = await mcp_client.list_tool_specs()
        for spec in specs:
            if spec.name in {"rag_search", "hr_query"}:
                continue
            tools.append({
                "type": "function",
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.input_schema or {"type": "object", "properties": {}},
            })
    except Exception as _exc:
        logger.warning("build_langgraph_tools_discovery_failed: %s", _exc)

    return tools


# ---------------------------------------------------------------------------
# Node: triage_node  (pre-tool router)
# ---------------------------------------------------------------------------

_TRIAGE_FALLBACK_CLARIFY = (
    "Bạn có thể mô tả rõ hơn câu hỏi của bạn không? "
    "Ví dụ: bạn muốn biết về chính sách gì, hoặc dữ liệu HR nào?"
)

# Backward-compat alias map: old 8-label names → new 5-label canonical names.
# Accepted on both sides so a mixed-version model output still routes correctly.
_RAG_NO_INFO_ANSWER = "Mình không tìm thấy thông tin này trong tài liệu nội bộ hiện có."
_RAG_NO_ACCESS_ANSWER = "Mình không tìm thấy tài liệu nội bộ mà bạn có quyền truy cập cho câu hỏi này."

_ROUTE_ALIAS: dict[str, str] = {
    # old safety labels → SAFETY
    "emergency": "safety",
    "injury": "safety",
    "distress": "safety",
    # old allow labels → ALLOW
    "in_scope": "allow",
    "it_support": "allow",
    # old refuse label → REFUSE
    "off_topic": "refuse",
    # old meta label → META
    "meta_conversation": "meta",
    # new labels pass through unchanged (lowercase match)
    "safety": "safety",
    "allow": "allow",
    "refuse": "refuse",
    "clarify": "clarify",
    "meta": "meta",
}


async def triage_node(state: AgentState, model: BaseChatModel) -> dict:
    """
    triage_node: Classify the question BEFORE calling any MCP tool.

    Routes (5 labels, allow-first principle):
      - SAFETY   -> shortcut_response = EMERGENCY/INJURY/DISTRESS_ANSWER (per safety_type),
                    shortcut_outcome = "SUCCESS"
      - META     -> shortcut_response = prior question from history, shortcut_outcome = "SUCCESS"
      - REFUSE   -> shortcut_response = next_offtopic_answer(), shortcut_outcome = "OFF_TOPIC"
      - CLARIFY  -> shortcut_response = LLM clarify question, shortcut_outcome = "CLARIFY"
      - ALLOW    -> returns {} (falls through to think_node)

    Old label aliases accepted for backward compatibility:
      emergency/injury/distress → SAFETY, in_scope/it_support → ALLOW,
      off_topic → REFUSE, meta_conversation → META.

    Uses TRIAGE_SYSTEM_PROMPT without bind_tools (classification only — no MCP call).
    On any parse/network error: defaults to ALLOW (never wrongly refuse a real question).
    """
    from langchain_core.messages import SystemMessage, HumanMessage

    question = state["question"]

    logger.info(
        "langgraph_triage_start",
        extra={"session_id": state["session_id"], "question": question[:120]},
    )

    try:
        # Include recent conversation history so follow-up queries have context.
        # History lives in state["messages"] (set by orchestration from conversation repo).
        history = list(state.get("messages") or [])
        messages = [SystemMessage(content=TRIAGE_SYSTEM_PROMPT)] + history + [HumanMessage(content=question)]
        response: AIMessage = await model.ainvoke(messages)
        raw = (response.content or "").strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = "\n".join(
                line for line in raw.splitlines()
                if not line.strip().startswith("```")
            ).strip()

        payload = json.loads(raw)
        route = str(payload.get("route", "allow")).strip().lower()
        reason = str(payload.get("reason", ""))

    except Exception as exc:
        # Log the raw model output so misformatted JSON is debuggable.
        raw_preview = locals().get("raw", "<not set>")
        if isinstance(raw_preview, str):
            raw_preview = raw_preview[:300]
        logger.warning(
            "langgraph_triage_error",
            extra={
                "session_id": state["session_id"],
                "error": str(exc),
                "raw_output": raw_preview,
            },
        )
        route = "allow"
        reason = f"parse_error_fallback: {exc}"

    logger.info(
        "langgraph_triage",
        extra={"session_id": state["session_id"], "route": route, "reason": reason[:120]},
    )

    # Normalise to canonical 5-label set using backward-compat alias map.
    # New label names (ALLOW/CLARIFY/REFUSE/SAFETY/META) pass through unchanged.
    canonical = _ROUTE_ALIAS.get(route, route)

    if canonical == "safety":
        # Read safety_type to select the correct pre-written canned answer.
        # When aliased from an old label name, override safety_type from the route itself
        # so old-label model outputs still dispatch to the right answer constant.
        safety_type = str(payload.get("safety_type", "")).strip().lower()  # type: ignore[possibly-undefined]
        if route == "emergency":
            safety_type = "emergency"
        elif route == "injury":
            safety_type = "injury"
        elif route == "distress":
            safety_type = "distress"

        if safety_type == "injury":
            safety_answer = INJURY_ANSWER
        elif safety_type == "distress":
            safety_answer = DISTRESS_ANSWER
        else:  # "emergency" or missing/unrecognised — default to emergency protocol
            safety_answer = EMERGENCY_ANSWER

        return {
            "shortcut_response": safety_answer,
            "shortcut_outcome": "SUCCESS",
            "phase": AgentPhase.DONE,
        }

    if canonical == "meta":
        # Look up the most recent prior user message in conversation history.
        # Skip any message that equals the current question — the save-ordering fix
        # ensures state["messages"] holds only prior turns, but the guard prevents
        # stale behaviour in edge cases where history is unavailable/stale.
        from langchain_core.messages import HumanMessage as _HM
        current_q = state["question"].strip()
        prev_q: str | None = None
        for msg in reversed(list(state.get("messages") or [])):
            if isinstance(msg, _HM):
                cand = str(msg.content or "").strip()
                if cand and cand != current_q:
                    prev_q = cand
                    break
        if prev_q:
            meta_answer = f'Câu hỏi trước của bạn là: "{prev_q}".'
        else:
            meta_answer = "Mình không tìm thấy câu hỏi nào trước đó trong lịch sử hội thoại."
        return {
            "shortcut_response": meta_answer,
            "shortcut_outcome": "SUCCESS",
            "phase": AgentPhase.DONE,
        }

    if canonical == "refuse":
        return {
            "shortcut_response": next_offtopic_answer(),
            "shortcut_outcome": "OFF_TOPIC",
            "phase": AgentPhase.DONE,
        }

    if canonical == "clarify":
        clarify_q = str(payload.get("clarify_question", "")).strip()  # type: ignore[possibly-undefined]
        return {
            "shortcut_response": clarify_q or _TRIAGE_FALLBACK_CLARIFY,
            "shortcut_outcome": "CLARIFY",
            "phase": AgentPhase.DONE,
        }

    # ALLOW (and any unrecognised label) — proceed to think_node
    return {}


# ---------------------------------------------------------------------------
# Node: shortcut_node
# ---------------------------------------------------------------------------

def shortcut_node(state: AgentState) -> dict:
    """
    Fast-path for identity, clarification, security, and off-topic queries.
    Returns shortcut_response + shortcut_outcome. No LLM call needed.
    Delegates to classify_shortcut() — single source of truth in shortcuts.py.
    """
    question = state["question"]
    result = classify_shortcut(question)

    if result is not None:
        response, outcome = result

        # USER_PROFILE_PLACEHOLDER: fill with actual user identity from auth state.
        if response == USER_PROFILE_PLACEHOLDER:
            role = state.get("user_role") or "không xác định"
            dept = state.get("user_department") or "không xác định"
            response = (
                f"Bạn đang đăng nhập với vai trò **{role}**, phòng ban **{dept}**."
            )

        shortcut_type = outcome.lower() if outcome != "SUCCESS" else "identity"
        logger.info("langgraph_shortcut", extra={"session_id": state["session_id"], "type": shortcut_type})
        return {
            "shortcut_response": response,
            "shortcut_outcome": outcome,
            "phase": AgentPhase.DONE,
        }

    # No shortcut matched — continue to triage_node (should not reach here if route_entry is correct)
    return {}


# ---------------------------------------------------------------------------
# Node: think_node
# ---------------------------------------------------------------------------

async def think_node(
    state: AgentState,
    model: BaseChatModel,
    mcp_client: MCPToolClient,
    tools_loader=None,
) -> dict:
    """
    think_node: LLM decides the next action.

    Inputs:  state["messages"] (LangGraph-managed message list)
    Outputs: state mutations (messages append, phase transition)

    Routing logic lives in the EDGES, not here.

    tools_loader: optional LangChainMCPToolsLoader; when provided its
        get_acl_tools() is used instead of build_langgraph_tools() so
        that tool descriptions are auto-discovered from the MCP server.
    """
    from langchain_core.messages import HumanMessage

    logger.info(
        "langgraph_think",
        extra={"session_id": state["session_id"], "iteration": state["iteration"]},
    )

    user_id = state["user_id"]
    allowed_doc_ids = frozenset(state["allowed_doc_ids"])

    if tools_loader is not None:
        tools = await tools_loader.get_acl_tools(
            user_id=user_id,
            allowed_doc_ids=allowed_doc_ids,
        )
    else:
        tools = await build_langgraph_tools(
            mcp_client=mcp_client,
            allowed_doc_ids=allowed_doc_ids,
            user_id=user_id,
        )

    # Append the current question so the LLM sees:
    #   [prior turn 1] [prior turn 2] ... [current question]
    # On second+ think iterations (after act_node), messages[-1] is a ToolMessage,
    # so check the LAST HumanMessage in the list to avoid re-appending the question.
    messages = list(state["messages"])
    q = state["question"]
    last_human = next((m for m in reversed(messages) if isinstance(m, HumanMessage)), None)
    if last_human is None or last_human.content != q:
        messages.append(HumanMessage(content=q))

    # If force_answer is set (iteration cap reached or duplicate tool call detected),
    # invoke the model WITHOUT tools so it MUST emit a final text answer synthesised
    # from the gathered ToolMessage context.  route_after_think will then route to
    # answer_node because there are no tool_calls in the response.
    if state.get("force_answer"):
        logger.info(
            "langgraph_think_forced_answer",
            extra={"session_id": state["session_id"], "iteration": state["iteration"]},
        )
        response: AIMessage = await model.ainvoke(messages)
    else:
        # tool_choice = "auto" (KHÔNG ép "required").
        # Trước đây ép "required" ở iteration 0 để model yếu không bỏ qua retrieval. NHƯNG
        # với ACTION tool (create_leave_request...) "required" gây 2 lỗi: (1) model bị ép gọi
        # NGAY khi chưa kịp điền args -> gọi rỗng {} -> hr 422; (2) chặn bước XÁC NHẬN (model
        # bị buộc gọi tool, không thể trả text hỏi lại). "auto" cho model: READ -> gọi
        # rag_search/hr_query (prompt RULES bắt buộc gọi tool khi cần data nội bộ); WRITE ->
        # hỏi xác nhận rồi mới gọi tool KÈM ĐỦ args. e2e (RAG sources>0 / HR) gác hồi quy read.
        bound_model = model.bind_tools(tools, tool_choice="auto")
        response: AIMessage = await bound_model.ainvoke(messages)

    tool_names = [tc["name"] for tc in (response.tool_calls or [])]
    logger.info(
        "langgraph_think_done",
        extra={
            "session_id": state["session_id"],
            "has_tool_calls": bool(response.tool_calls),
            "tool_names": tool_names,
            "content_length": len(response.content or ""),
        },
    )

    return {
        "messages": [response],
        "phase": AgentPhase.THINKING,
        "previous_phase": state["phase"],
    }


# ---------------------------------------------------------------------------
# Node: act_node
# ---------------------------------------------------------------------------

async def act_node(
    state: AgentState,
    mcp_client: MCPToolClient,
) -> dict:
    """
    act_node: Execute one tool call with ACL guard (async version).

    ACL GUARD: user_id and allowed_doc_ids come from state (set at entry),
    never from LLM arguments. This prevents privilege escalation.

    Returns a ToolMessage added to the message history.
    """
    last_msg: AIMessage = state["messages"][-1]

    if not last_msg.tool_calls:
        return {"phase": AgentPhase.ACTING}

    tool_call = last_msg.tool_calls[0]
    tool_name = tool_call["name"]
    tool_args = tool_call.get("args", {})
    tool_call_id = tool_call.get("id", f"call_{tool_name}")

    # For rag_search: log the actual query being sent (state["question"]), not the LLM-suggested
    # tool arg (which is ignored).  This makes traces unambiguous in Langfuse.
    actual_query = state["question"] if tool_name == "rag_search" else None
    logger.info(
        "langgraph_act",
        extra={
            "session_id": state["session_id"],
            "tool": tool_name,
            "args_keys": list(tool_args.keys()),
            **({"query": actual_query} if actual_query is not None else {}),
        },
    )

    allowed_doc_ids = frozenset(state["allowed_doc_ids"])
    user_id = state["user_id"]

    # Dedup guard: if we have already executed this exact (tool, args) pair in a prior
    # iteration, set force_answer so think_node will emit a final text response instead
    # of looping again.  We still execute the tool this time so the LLM has the result.
    existing_sigs = list(state.get("tool_call_signatures") or [])
    try:
        sig = f"{tool_name}:{json.dumps(tool_args, sort_keys=True)}"
    except (TypeError, ValueError):
        sig = f"{tool_name}:{str(sorted(tool_args.items()))}"
    is_duplicate = sig in existing_sigs
    new_sigs = existing_sigs + [sig]

    # Observability: filled by rag_search branch, None for all other tools.
    _rag_event: dict | None = None
    hard_stop_response: str | None = None

    try:
        if tool_name == "rag_search":
            if not allowed_doc_ids:
                data = json.dumps({"error": "No document access"})
                success = False
                new_sources = []
                hard_stop_response = _RAG_NO_ACCESS_ANSWER
            else:
                # top_k ưu tiên từ LLM tool_args, fallback về giá trị config-driven trong state.
                effective_top_k = tool_args.get("top_k", state.get("rag_top_k", 5))
                _rag_start_dt = datetime.now(timezone.utc)
                results = await mcp_client.rag_search(
                    query=state["question"],  # raw question — server-injected, like user_id
                    document_ids=list(allowed_doc_ids),
                    top_k=effective_top_k,
                )
                _rag_end_dt = datetime.now(timezone.utc)
                _threshold = state.get("rag_score_threshold", 0.45)
                qualified = [r for r in results if r.score >= _threshold]

                # Ghi debug event (JSON-safe) vào state để orchestration dựng Langfuse span.
                # Tất cả giá trị là scalar/list[str/float] — an toàn với checkpointer.
                _rag_event = {
                    "query": state["question"],
                    "top_k": effective_top_k,
                    "allowed_count": len(allowed_doc_ids),
                    "total": len(results),
                    "qualified": len(qualified),
                    "scores": [round(r.score, 4) for r in results[:10]],
                    "doc_names": sorted({r.document_name for r in qualified}),
                    "start": _rag_start_dt.isoformat(),
                    "end": _rag_end_dt.isoformat(),
                }

                if qualified:
                    start_ref = state.get("source_ref_counter", 0)
                    data = json.dumps({
                        "results": [
                            {
                                "ref": start_ref + i + 1,
                                "document_name": r.document_name,
                                "caption": r.caption,
                                "parent_text": r.parent_text,
                                "heading_path": r.heading_path,
                                "page_number": r.page_number,
                            }
                            for i, r in enumerate(qualified)
                        ]
                    })
                    success = True
                    new_sources = [
                        SourceDoc(
                            document_name=r.document_name,
                            caption=r.caption,
                            heading_path=r.heading_path,
                            score=r.score,
                            source_gcs_uri=r.source_gcs_uri,
                            document_id=r.document_id,
                            page_number=r.page_number,
                            ref=start_ref + i + 1,
                            chunk_id=r.chunk_id,
                        )
                        for i, r in enumerate(qualified)
                    ]
                elif results:
                    # Adaptive fallback: có kết quả nhưng dưới ngưỡng -> pass cho LLM tự đánh giá
                    start_ref = state.get("source_ref_counter", 0)
                    data = json.dumps({
                        "results": [
                            {
                                "ref": start_ref + i + 1,
                                "document_name": r.document_name,
                                "caption": r.caption,
                                "parent_text": r.parent_text,
                                "heading_path": r.heading_path,
                                "page_number": r.page_number,
                            }
                            for i, r in enumerate(results)
                        ]
                    })
                    success = True
                    new_sources = [
                        SourceDoc(
                            document_name=r.document_name,
                            caption=r.caption,
                            heading_path=r.heading_path,
                            score=r.score,
                            source_gcs_uri=r.source_gcs_uri,
                            document_id=r.document_id,
                            page_number=r.page_number,
                            ref=start_ref + i + 1,
                            chunk_id=r.chunk_id,
                        )
                        for i, r in enumerate(results)
                    ]
                else:
                    # Hoàn toàn trống -> hard-stop NO_INFO
                    data = json.dumps({
                        "results": [],
                        "message": _RAG_NO_INFO_ANSWER,
                    }, ensure_ascii=False)
                    success = False
                    new_sources = []
                    hard_stop_response = _RAG_NO_INFO_ANSWER

        elif tool_name == "hr_query":
            # KHÔNG cần intent từ LLM: lấy TOÀN BỘ hồ sơ HR (mcp -> /hr/profile),
            # user_id tiêm server-side (ACL). Trả full data JSON cho LLM tự nhặt phần
            # liên quan -> hết failure mode "intent rỗng". call_tool đi qua breaker.
            raw = await mcp_client.call_tool("hr_query", {"user_id": user_id})
            if isinstance(raw, dict) and raw.get("error"):
                data = json.dumps(raw, ensure_ascii=False)
                success = False
            else:
                payload = raw.get("data", raw) if isinstance(raw, dict) else raw
                data = json.dumps(payload, ensure_ascii=False)
                success = bool(payload) and data not in ("{}", "null", "")
            new_sources = []

        else:
            # Generic tool (summary-style): call_tool + extract summary.
            # user_id is injected server-side; mcp-service tools should ignore
            # unknown kwargs they don't declare.
            raw = await mcp_client.call_tool(
                tool_name,
                {**tool_args, "user_id": user_id},
            )
            summary = str(
                raw.get("summary") or raw.get("answer") or raw.get("text") or ""
            )
            if not summary and isinstance(raw, dict):
                summary = json.dumps(raw, ensure_ascii=False)
            data = summary
            success = bool(summary and summary not in ("{}", "null", ""))
            new_sources = []

    except MCPCircuitOpenError as exc:
        logger.warning(
            "langgraph_act_circuit_open",
            extra={"session_id": state["session_id"], "tool": tool_name, "error": str(exc)},
        )
        data = json.dumps({"error": "MCP service temporarily unavailable (circuit open)"})
        success = False
        new_sources = []
        if tool_name == "rag_search":
            hard_stop_response = _RAG_NO_INFO_ANSWER
    except Exception as exc:
        logger.error(
            "langgraph_act_error",
            extra={"session_id": state["session_id"], "tool": tool_name, "error": str(exc)},
        )
        data = f"Loi khi thuc thi tool: {exc}"
        success = False
        new_sources = []
        if tool_name == "rag_search":
            hard_stop_response = _RAG_NO_INFO_ANSWER

    tool_message = ToolMessage(
        content=data,
        tool_call_id=tool_call_id,
        name=tool_name,
    )

    tool_result = ToolCallResult(
        tool_name=tool_name,
        success=success,
        data=data,
        error=None if success else data,
    )

    existing_sources = state.get("sources") or []
    new_state: dict = {
        "messages": [tool_message],
        "phase": AgentPhase.ACTING,
        "previous_phase": state["phase"],
        "tool_results": state.get("tool_results", []) + [tool_result],
        "tool_call_signatures": new_sigs,
    }

    # Duplicate tool call detected — force final text answer on the next think iteration.
    if is_duplicate:
        logger.info(
            "langgraph_act_duplicate_tool_call",
            extra={"session_id": state["session_id"], "tool": tool_name, "sig": sig[:120]},
        )
        new_state["force_answer"] = True

    if tool_name == "rag_search" and success:
        seen_chunks = {s["chunk_id"] for s in existing_sources}
        deduped = existing_sources + [
            s for s in new_sources if s["chunk_id"] not in seen_chunks
        ]
        new_state["sources"] = deduped
        new_state["source_ref_counter"] = state.get("source_ref_counter", 0) + len(new_sources)
    elif tool_name == "rag_search" and not success:
        new_state["sources"] = existing_sources
        new_state["shortcut_response"] = hard_stop_response or _RAG_NO_INFO_ANSWER
        new_state["shortcut_outcome"] = "NO_INFO"
        new_state["phase"] = AgentPhase.DONE

    # Observability accumulator: append rag_search debug event if recorded above.
    if _rag_event is not None:
        new_state["rag_search_events"] = list(state.get("rag_search_events") or []) + [_rag_event]

    return new_state


# ---------------------------------------------------------------------------
# Node: observe_node
# ---------------------------------------------------------------------------

def observe_node(state: AgentState) -> dict:
    """
    observe_node: Log tool result and prepare for next LLM turn.

    Increments iteration counter. The loop continues in think_node.
    """
    last_msg = state["messages"][-1]
    tool_name = getattr(last_msg, "name", "unknown")

    new_iteration = state["iteration"] + 1

    logger.info(
        "langgraph_observe",
        extra={
            "session_id": state["session_id"],
            "iteration": state["iteration"],
            "next_iteration": new_iteration,
            "tool": tool_name,
            "total_tools": len(state.get("tool_results", [])) + 1,
        },
    )

    result: dict = {
        "phase": AgentPhase.OBSERVING,
        "previous_phase": state["phase"],
        "iteration": new_iteration,
    }

    # Iteration cap reached — tell think_node to produce the final answer without
    # calling any more tools. This makes the loop hard-bounded at max_iterations.
    if new_iteration >= state["max_iterations"]:
        logger.info(
            "langgraph_observe_cap_reached",
            extra={
                "session_id": state["session_id"],
                "iteration": new_iteration,
                "max_iterations": state["max_iterations"],
            },
        )
        result["force_answer"] = True

    return result


# ---------------------------------------------------------------------------
# Node: answer_node
# ---------------------------------------------------------------------------

def answer_node(state: AgentState) -> dict:
    """
    answer_node: Mark the end of the agent run.

    - shortcut path: uses state["shortcut_response"] directly
    - think path: LLM already gave content in the last AIMessage

    Phase is set to DONE so the SSE stream knows to emit the final event.
    """
    outcome = state.get("shortcut_outcome") or "SUCCESS"
    has_tool_calls = bool(state.get("tool_results"))

    logger.info(
        "langgraph_answer",
        extra={
            "session_id": state["session_id"],
            "iteration": state["iteration"],
            "outcome": outcome,
            "sources_count": len(state.get("sources", [])),
            "has_tool_calls": has_tool_calls,
        },
    )

    return {
        "phase": AgentPhase.DONE,
        "previous_phase": state["phase"],
    }
