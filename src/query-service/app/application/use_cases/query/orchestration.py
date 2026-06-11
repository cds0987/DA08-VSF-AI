from collections.abc import AsyncIterator
import hashlib
import json
import logging
import re
from time import perf_counter
from typing import Any
import unicodedata
from uuid import uuid4

from app.application.langgraph_state import create_initial_state, AgentPhase
from app.application.ports import (
    AuthenticatedUser,
    HrQueryResultLike,
    LLMStreamingClient,
    MCPToolClient,
    RouteDecisionProvider,
    SearchResultLike,
    SemanticCache,
    ToolDecisionClient,
)
from app.application.route_decision import RouteDecision, coerce_route_decision
from app.domain.outcome import Outcome
from app.domain.repositories.conversation_repository import ConversationRepository
from app.domain.repositories.document_access_repository import DocumentAccessRepository
from app.infrastructure.config import Settings


logger = logging.getLogger(__name__)


# Numeric enum values match the reference REACT agent convention:
#   REFUSE=1, CLARIFY=2, NO_INFO=3, OFF_TOPIC=4, SUCCESS=5
_OUTCOME_ENUM_MAP: dict[str, int] = {
    "REFUSE": Outcome.REFUSE.value,       # 1
    "CLARIFY": Outcome.CLARIFY.value,     # 2
    "NO_INFO": Outcome.NO_INFO.value,      # 3
    "OFF_TOPIC": Outcome.OFF_TOPIC.value,  # 4
    "SUCCESS": Outcome.SUCCESS.value,      # 5
    "ERROR": Outcome.ERROR.value,         # 6
}


def _outcome_to_enum_value(outcome_str: str) -> int:
    """Convert outcome string to numeric enum value for SSE compatibility."""
    return _OUTCOME_ENUM_MAP.get(outcome_str.upper(), Outcome.SUCCESS.value)


class QueryOrchestrationUseCase:
    def __init__(
        self,
        settings: Settings,
        conversation_repo: ConversationRepository,
        document_access_repo: DocumentAccessRepository,
        semantic_cache: SemanticCache,
        mcp_client: MCPToolClient,
        openai_client: LLMStreamingClient,
        route_decision_provider: RouteDecisionProvider | ToolDecisionClient | None = None,
        tool_decision_client: ToolDecisionClient | None = None,
        langgraph_agent=None,
        langfuse_tracer=None,
        guardrails=None,
    ) -> None:
        self._settings = settings
        self._conversation_repo = conversation_repo
        self._document_access_repo = document_access_repo
        self._semantic_cache = semantic_cache
        self._mcp_client = mcp_client
        self._openai_client = openai_client
        self._langgraph_agent = langgraph_agent
        self._tracer = langfuse_tracer
        # guardrails is a (InputGuardrail, OutputGuardrail) tuple or None
        if guardrails is not None:
            self._input_guardrail, self._output_guardrail = guardrails
        else:
            from app.infrastructure.guardrails.llm_guard_service import (
                NoOpInputGuardrail, NoOpOutputGuardrail,
            )
            self._input_guardrail = NoOpInputGuardrail()
            self._output_guardrail = NoOpOutputGuardrail()
        if route_decision_provider is None and tool_decision_client is None:
            raise ValueError("A route decision provider is required")
        self._route_decision_provider = route_decision_provider or tool_decision_client

    async def stream(
        self,
        question: str,
        user: AuthenticatedUser,
        trace_session: str | None = None,
        conversation_title: str | None = None,
    ) -> AsyncIterator[dict]:
        """Wrapper mỏng: bọc luồng thật bằng 1 langfuse trace + node spans (best-effort,
        low-level client — KHÔNG callback).

        trace_session: nếu set (vd "ci-smoke" do smoke CI), dùng làm session_id của TRACE
        thay cho session_id ngẫu nhiên -> gom trace smoke 1 chỗ để deploy kế tự xóa."""
        tracer = self._tracer
        session_id = str(uuid4())
        # Tạo trace eagerly (trước event loop) để span_start() trong _stream_langgraph
        # có trace object ngay từ event đầu tiên.
        trace = tracer.start(question, user, trace_session or session_id, conversation_title=conversation_title) if tracer else None
        last_done: dict | None = None
        usage_meta: dict | None = None
        try:
            async for event in self._stream_inner(question, user, session_id, trace):
                if event.get("done"):
                    # _usage/_answer là kênh nội bộ (token/model/answer cho langfuse) —
                    # pop ra để KHÔNG rò xuống SSE/frontend; chỉ tracer dùng.
                    usage_meta = event.pop("_usage", None)
                    last_done = {**event}  # copy trước khi pop _answer (tracer cần)
                    event.pop("_answer", None)
                yield event
        finally:
            if tracer is not None and trace is not None:
                tracer.finish(trace, last_done, usage_meta)

    async def _stream_inner(
        self,
        question: str,
        user: AuthenticatedUser,
        session_id: str,
        trace_handle: Any = None,
    ) -> AsyncIterator[dict]:
        started = perf_counter()

        # Input guardrail — block prompt injection before touching the LLM or MCP.
        blocked, reason = await self._input_guardrail.scan(question)
        if blocked:
            logger.warning(
                "guardrail_input_blocked",
                extra={"user_id": user.id, "session_id": session_id, "reason": reason},
            )
            yield {
                "done": True,
                "outcome": Outcome.REFUSE.value,
                "sources": [],
                "session_id": session_id,
                "guardrail": reason,
            }
            return

        # NOTE: user question is saved AFTER context is fetched so that
        # state["messages"] contains only prior turns (not the current question).
        # Each path below saves the question right after the context fetch.

        # LangGraph path (canonical) — requires use_langgraph=True and a built agent.
        # Falls through to the legacy direct-orchestration path when no agent is available
        # (e.g. mock mode / no OpenAI key).
        if self._langgraph_agent is not None:
            async for event in self._stream_langgraph(
                question, user, session_id, started,
                tracer=self._tracer, trace_handle=trace_handle,
            ):
                yield event
            return

        # Legacy path: direct orchestration without agent (mock/test mode)
        context = await self._conversation_repo.get_context(user.id, recent_k=5)
        recent_messages = [(message.role, message.content) for message in context.recent_messages]
        await self._conversation_repo.save_message(user.id, "user", question)
        decision = await self._choose_route(question, recent_messages)

        # Handle direct responses for clarification or out of scope
        if decision.decision in {"clarification", "identity_shortcut", "out_of_scope", "off_topic"}:
            async for event in self._handle_direct_response(
                user.id,
                session_id,
                started,
                str(decision.direct_response or ""),
                decision.outcome,
            ):
                yield event
            return

        # If the routing decision indicates a non-success outcome, use fallback with appropriate message
        if decision.outcome != Outcome.SUCCESS:
            async for event in self._fallback(
                user.id, session_id, started, decision.outcome,
                question=question, recent_messages=recent_messages,
            ):
                yield event
            return

        if decision.decision == "hr_query":
            intent = str(decision.tool_arguments.get("intent", "leave_balance"))
            if self._settings.tool_routing_mode.strip().lower() == "native":
                async for event in self._handle_generic_tool(
                    tool_name="hr_query",
                    arguments={"user_id": user.id, "intent": intent},
                    user=user,
                    session_id=session_id,
                    started=started,
                    outcome=decision.outcome,
                ):
                    yield event
            else:
                async for event in self._handle_hr(
                    question=question,
                    user=user,
                    intent=intent,
                    recent_messages=recent_messages,
                    session_id=session_id,
                    started=started,
                    outcome=decision.outcome,
                ):
                    yield event
            return

        # Generic tool: discovered from mcp-service but not rag_search or hr_query.
        # Routed here when route_decision returns a tool name that is not one of the
        # two bespoke tools. Executed via call_tool() + summary-style response.
        if decision.decision not in {"rag_search", "hr_query"}:
            arguments = {**decision.tool_arguments, "user_id": user.id}
            async for event in self._handle_generic_tool(
                tool_name=decision.decision,
                arguments=arguments,
                user=user,
                session_id=session_id,
                started=started,
                outcome=decision.outcome,
            ):
                yield event
            return

        async for event in self._handle_rag(
            question=question,
            search_query=str(decision.tool_arguments.get("query") or question),
            user=user,
            recent_messages=recent_messages,
            session_id=session_id,
            started=started,
            outcome=decision.outcome,
        ):
            yield event

    async def _stream_langgraph(
        self,
        question: str,
        user: AuthenticatedUser,
        session_id: str,
        started: float,
        tracer: Any = None,
        trace_handle: Any = None,
    ) -> AsyncIterator[dict]:
        """
        Stream responses using the LangGraph agent.
        Uses astream_events for full granularity: token-level SSE + tool lifecycle events.
        Emits events compatible with the reference REACT agent format:
          - token events with phase, agent_mode, session_id, iterations
          - tool events (acting/observing) with phase, agent_mode, session_id, iterations
          - done event with outcome numeric enum, sources, agent_mode, iterations
        """
        from langchain_core.messages import HumanMessage, AIMessage as LCAIMessage

        allowed_doc_ids = await self._document_access_repo.get_allowed_doc_ids(
            user_id=user.id,
            role=user.role,
            department=user.department,
            account_type=user.account_type,
        )

        # Fetch recent conversation turns for context (follow-up queries like "Ngày mai").
        # IMPORTANT: fetch history BEFORE saving the current question so that
        # state["messages"] contains only prior turns.
        recent_lc_messages: list = []
        try:
            ctx = await self._conversation_repo.get_context(user.id, recent_k=4)
            for msg in ctx.recent_messages:
                if msg.role == "user":
                    recent_lc_messages.append(HumanMessage(content=msg.content))
                elif msg.role == "assistant":
                    recent_lc_messages.append(LCAIMessage(content=msg.content))
        except Exception:
            pass  # history is optional — never block the current query

        # Save current question NOW (after the history snapshot is taken).
        await self._conversation_repo.save_message(user.id, "user", question)

        initial_state = create_initial_state(
            question=question,
            user_id=user.id,
            user_role=user.role,
            user_department=user.department,
            allowed_doc_ids=list(allowed_doc_ids) if allowed_doc_ids else [],
            session_id=session_id,
            max_iterations=self._settings.agent_max_iterations,
            recent_messages=recent_lc_messages,
            rag_score_threshold=self._settings.rag_score_threshold,
        )

        answer_accumulator: list[str] = []
        # Track which node/name the last iteration was in, to derive a stable iteration count
        last_iteration = 0
        # Track if we already emitted the shortcut acting event
        shortcut_acting_emitted = False
        # Langfuse node spans: name -> [span, ...] (LIFO stack per name).
        # Dùng name thay vì run_id vì LangGraph có thể emit on_chain_end với run_id
        # khác on_chain_start (dispatcher wrapper). LangGraph chạy node tuần tự nên
        # LIFO stack là đủ chính xác.
        _active_spans: dict[str, list] = {}
        _SPAN_NODES = {"shortcut", "triage", "think", "act", "observe", "answer"}
        # Gom usage từ MỌI model call (on_chat_model_end) — gồm cả triage. _collect_usage
        # cũ chỉ đọc final_state["messages"] nên off-topic (triage không vào messages) ra
        # 0 token -> trace $0.00 dù triage vẫn tốn tiền. Accumulator này phủ mọi path.
        _usage_acc: dict[str, Any] = {"input": 0, "output": 0, "cached": 0, "model": None}

        # recursion_limit is a defence-in-depth net; Part 1 (force_answer + act→observe→think
        # wiring) provides the logical hard cap.  Set to 3 * max_iterations + overhead.
        # NOTE: langfuse tracing giờ làm ở wrapper stream() bằng low-level client (KHÔNG
        # còn callback gắn vào run_config — callback v2 xung đột langchain-core 1.x).
        _recursion_limit = max(12, self._settings.agent_max_iterations * 4 + 4)
        run_config: dict = {
            "recursion_limit": _recursion_limit,
        }

        _GRACEFUL_CRASH_MSG = (
            "Mình chưa xử lý được yêu cầu này, bạn thử diễn đạt lại ngắn gọn hơn nhé."
        )

        try:
            async for event in self._langgraph_agent.astream_events(
                initial_state, version="v2", config=run_config
            ):
                event_type = event["event"]

                # Node enter event — derive iteration count from the node name
                if event_type == "on_chain_start":
                    node_name = event.get("name", "")
                    # act_node and observe_node represent actual tool-call iterations
                    # think_node enters before the LLM call; answer_node is the final step (no iteration increment)
                    if node_name in ("act", "observe"):
                        last_iteration = max(last_iteration, 1)
                    # NOTE: do NOT increment for "think" or "answer" — shortcut path has 0 iterations
                    if node_name in _SPAN_NODES and tracer and trace_handle:
                        _span = tracer.span_start(
                            trace_handle, name=node_name,
                            input_data={"iteration": last_iteration},
                        )
                        if _span:
                            _active_spans.setdefault(node_name, []).append(_span)
                        # Tool span: agent gọi tool THẲNG trong act_node (KHÔNG qua LangChain
                        # ToolNode) nên on_tool_start/on_tool_end KHÔNG bao giờ bắn. Lấy
                        # tool call từ chính input state của act_node để vẫn có span
                        # `tool.<name>` (args lúc mở, result lúc act_node xong).
                        if node_name == "act":
                            _tc = _extract_tool_call(event)
                            if _tc:
                                # Lồng tool span VÀO TRONG act span vừa mở.
                                _act_parent = (_active_spans.get("act") or [None])[-1]
                                _tspan = tracer.span_start(
                                    trace_handle, name=f"tool.{_tc['name']}",
                                    input_data={"tool": _tc["name"], "args": _tc.get("args", {})},
                                    parent=_act_parent,
                                )
                                if _tspan:
                                    _active_spans.setdefault(f"tool.{_tc['name']}", []).append(_tspan)

                # Model call bắt đầu — bắt ĐÚNG prompt model NHẬN (system + context +
                # tool results + history). Mở span llm.<node> để thấy "model nhận gì".
                elif event_type == "on_chat_model_start":
                    if tracer and trace_handle:
                        _node = (event.get("metadata") or {}).get("langgraph_node") or "call"
                        # Lồng span llm.<node> VÀO TRONG node span tương ứng (think/triage/
                        # answer) để cây trace gọn: click node -> thấy ngay model I/O.
                        _parent = (_active_spans.get(_node) or [None])[-1]
                        _mspan = tracer.span_start(
                            trace_handle, name=f"llm.{_node}",
                            input_data=_render_chat_input(event),
                            parent=_parent,
                        )
                        if _mspan:
                            _active_spans.setdefault("llm.call", []).append(_mspan)

                # Model call xong — bắt output THẬT (reasoning/answer + tool_calls quyết
                # định gọi tool nào). Đóng span để thấy "model nghĩ gì".
                elif event_type == "on_chat_model_end":
                    if tracer:
                        _mstack = _active_spans.get("llm.call")
                        if _mstack:
                            tracer.span_end(_mstack.pop(), output_data=_render_chat_output(event))
                    # Cộng dồn token của LẦN GỌI NÀY (triage/think/answer) vào rollup.
                    _accumulate_usage(_usage_acc, event)

                # Token stream from LLM
                elif event_type == "on_chat_model_stream":
                    token = event["data"]["chunk"].content
                    if token:
                        answer_accumulator.append(token)
                        # Detect phase from content (ReAct markers)
                        current_phase = "generating"
                        stripped = token.lstrip()
                        if stripped.startswith("THOUGHT:"):
                            current_phase = "thinking"
                        elif stripped.startswith("ACTION:") or stripped.startswith("OBSERVATION:"):
                            current_phase = "observing"
                        yield {
                            "token": token,
                            "phase": current_phase,
                            "agent_mode": "langgraph",
                            "session_id": session_id,
                            "iterations": last_iteration,
                        }

                # Tool call started
                elif event_type == "on_tool_start":
                    tool_name = event["name"]
                    input_data = event.get("data", {}).get("input", {})
                    if tracer and trace_handle:
                        _span = tracer.span_start(
                            trace_handle, name=f"tool.{tool_name}",
                            input_data={"tool": tool_name, "args": input_data},
                        )
                        if _span:
                            _active_spans.setdefault(f"tool.{tool_name}", []).append(_span)
                    yield {
                        "phase": "acting",
                        "agent_mode": "langgraph",
                        "session_id": session_id,
                        "iterations": last_iteration,
                        "tool": tool_name,
                        "tool_args": input_data,
                    }

                # Tool call completed
                elif event_type == "on_tool_end":
                    tool_name = event["name"]
                    output_data = event.get("data", {}).get("output", "")
                    if tracer:
                        _tool_stack = _active_spans.get(f"tool.{tool_name}")
                        if _tool_stack:
                            _span = _tool_stack.pop()
                            tracer.span_end(_span, output_data={"result_preview": str(output_data)[:300]})
                    yield {
                        "phase": "observing",
                        "agent_mode": "langgraph",
                        "session_id": session_id,
                        "iterations": last_iteration,
                        "tool": tool_name,
                        "tool_result": str(output_data)[:200] if output_data else "",
                    }

                # Graph error — LLM failure or unhandled exception
                elif event_type == "on_chain_error":
                    error_val = event.get("data", {}).get("error")
                    error_msg = str(getattr(error_val, "args", [str(error_val)])[0])
                    if tracer:
                        for key, stack in list(_active_spans.items()):
                            while stack:
                                _span = stack.pop()
                                tracer.span_end(_span, output_data={"error": error_msg, "span": key}, level="ERROR")
                        err_span = tracer.span_start(
                            trace_handle,
                            name="graph.error",
                            input_data={"node": event.get("name")},
                        ) if trace_handle else None
                        tracer.span_end(err_span, output_data={"error": error_msg}, level="ERROR")
                    logger.error(
                        "langgraph_stream_error",
                        extra={"session_id": session_id, "error": error_msg},
                    )
                    await self._save_assistant(
                        user.id, session_id,
                        f"Loi he thong: {error_msg}",
                        [], started,
                    )
                    yield {
                        "error": error_msg,
                        "done": True,
                        "sources": [],
                        "session_id": session_id,
                        "outcome": Outcome.ERROR.value,
                        "agent_mode": "langgraph",
                        "iterations": max(last_iteration, 1),
                    }
                    return

                # Graph complete — only the top-level graph on_chain_end is final
                elif event_type == "on_chain_end":
                    run_name = event.get("name", "")
                    if run_name not in ("VinSmartFutureReActAgent", "VinSmartFutureAgent"):
                        # Sub-node completed — close its Langfuse span (LIFO pop by name)
                        if tracer:
                            _out = event.get("data", {}).get("output") or {}
                            _node_stack = _active_spans.get(run_name)
                            if _node_stack:
                                _span = _node_stack.pop()
                                tracer.span_end(_span, output_data=_node_output_summary(_out))
                            # Đóng span tool mở ở act_node (result = output của act_node:
                            # sources/phase...). on_tool_end không bắn nên đóng tại đây.
                            if run_name == "act":
                                for _k in [k for k in _active_spans if k.startswith("tool.")]:
                                    _tstack = _active_spans.get(_k)
                                    while _tstack:
                                        tracer.span_end(
                                            _tstack.pop(),
                                            output_data=_node_output_summary(_out),
                                        )
                        continue

                    final_state = event.get("data", {}).get("output", {})
                    if isinstance(final_state, dict):
                        shortcut_response = final_state.get("shortcut_response")
                        shortcut_outcome = final_state.get("shortcut_outcome") or "SUCCESS"

                        # Shortcut path — emit acting event then token stream
                        if shortcut_response:
                            # Emit one acting event to signal shortcut before streaming answer
                            if not shortcut_acting_emitted:
                                yield {
                                    "phase": "acting",
                                    "agent_mode": "langgraph",
                                    "session_id": session_id,
                                    "iterations": 0,
                                    "tool": "shortcut_off_topic",
                                    "tool_args": {"outcome": shortcut_outcome},
                                }
                                shortcut_acting_emitted = True

                            for token in _word_chunks(shortcut_response):
                                yield {
                                    "token": token,
                                    "phase": "generating",
                                    "agent_mode": "langgraph",
                                    "session_id": session_id,
                                    "iterations": 0,
                                }
                            answer = shortcut_response
                        else:
                            # answer_accumulator is empty when the model adapter uses non-streaming
                            # ainvoke (OpenAIResponsesChatModel has no _astream, so astream_events
                            # never emits on_chat_model_stream events).  Recover the answer directly
                            # from the final AIMessage in the state's message list.
                            if not answer_accumulator:
                                messages_in_state = final_state.get("messages", [])
                                for msg in reversed(messages_in_state):
                                    content = getattr(msg, "content", "") or ""
                                    tool_calls = getattr(msg, "tool_calls", None) or []
                                    if content and not tool_calls:
                                        # Strip any leaked ReAct marker lines before streaming.
                                        clean = _strip_agent_markers(content)
                                        if not clean:
                                            # Sanitizer removed everything — treat as no answer.
                                            break
                                        # Stream the recovered answer as token events so the UI
                                        # receives incremental updates, matching the shortcut path.
                                        for token in _word_chunks(clean):
                                            yield {
                                                "token": token,
                                                "phase": "generating",
                                                "agent_mode": "langgraph",
                                                "session_id": session_id,
                                                "iterations": last_iteration,
                                            }
                                        answer_accumulator.append(clean)
                                        break

                            answer = "".join(answer_accumulator)

                            # If LLM returned nothing at all, emit NO_INFO instead of empty SUCCESS
                            if not answer:
                                shortcut_outcome = "NO_INFO"

                        sources = final_state.get("sources", [])
                        # shortcut path: 0 iterations; think path: iterations = number of act/observe runs
                        final_iteration = 0 if shortcut_response else max(last_iteration, 1)
                        # Override outcome to NO_INFO if the answer is a generic fallback
                        if answer and _is_fallback_answer(answer) and shortcut_outcome == "SUCCESS":
                            shortcut_outcome = "NO_INFO"
                        outcome_value = _outcome_to_enum_value(shortcut_outcome)

                        # Output guardrail — redact PII from final answer before persisting/sending.
                        answer = await self._output_guardrail.redact(answer)

                        await self._save_assistant(user.id, session_id, answer, sources, started)
                        done_event = {
                            "done": True,
                            "sources": sources,
                            "session_id": session_id,
                            "outcome": outcome_value,
                            "agent_mode": "langgraph",
                            "iterations": final_iteration,
                            "_answer": answer,  # kênh nội bộ cho langfuse tracer
                        }
                        # Token/model usage cho langfuse (cost+latency). Kênh nội bộ _usage:
                        # wrapper stream() pop ra trước khi yield SSE -> KHÔNG rò xuống FE.
                        # Ưu tiên accumulator (gom MỌI model call gồm triage); fallback
                        # _collect_usage cho path không qua on_chat_model_end (mock/non-stream).
                        usage_meta = _usage_from_acc(_usage_acc, self._settings.openai_llm_model) \
                            or _collect_usage(final_state, self._settings.openai_llm_model)
                        if usage_meta is not None:
                            done_event["_usage"] = usage_meta
                        yield done_event
                        return

        except Exception as _stream_exc:
            # Catch GraphRecursionError and any unexpected crash mid-stream.
            # Saving an assistant turn completes the exchange so the frontend does NOT
            # resend the user message (which would cause duplicates).
            _err_name = type(_stream_exc).__name__
            if tracer:
                for key, stack in list(_active_spans.items()):
                    while stack:
                        _span = stack.pop()
                        tracer.span_end(
                            _span,
                            output_data={"error": str(_stream_exc), "span": key},
                            level="ERROR",
                        )
                err_span = tracer.span_start(
                    trace_handle,
                    name="graph.error",
                    input_data={"node": "langgraph_stream"},
                ) if trace_handle else None
                tracer.span_end(err_span, output_data={"error": str(_stream_exc)}, level="ERROR")
            logger.error(
                "langgraph_stream_fatal %s: %s",
                _err_name,
                str(_stream_exc)[:400],
                extra={"session_id": session_id, "error_type": _err_name},
                exc_info=True,
            )
            await self._save_assistant(user.id, session_id, _GRACEFUL_CRASH_MSG, [], started)
            yield {
                "error": _err_name,
                "done": True,
                "sources": [],
                "session_id": session_id,
                "outcome": Outcome.NO_INFO.value,
                "agent_mode": "langgraph",
                "iterations": max(last_iteration, 1),
            }

    async def _choose_route(
        self,
        question: str,
        recent_messages: list[tuple[str, str]],
    ) -> RouteDecision:
        try:
            available_tools = await self._mcp_client.list_tools()
            discovered_tools = set(available_tools)
            choose_route = getattr(self._route_decision_provider, "choose_route", None)
            if choose_route is not None:
                raw_decision = await choose_route(
                    question=question,
                    recent_messages=recent_messages,
                    available_tools=available_tools,
                )
            else:
                raw_decision = await self._route_decision_provider.choose_tool(
                    question=question,
                    recent_messages=recent_messages,
                    available_tools=available_tools,
                )
        except Exception:
            return RouteDecision(
                decision="rag_search",
                tool_arguments={"query": question},
                reason="route decision failed",
                confidence=0.0,
            )

        return coerce_route_decision(
            raw_decision,
            default_query=question,
            discovered_tools=discovered_tools,
        )

    async def _handle_rag(
        self,
        question: str,
        search_query: str,
        user: AuthenticatedUser,
        recent_messages: list[tuple[str, str]],
        session_id: str,
        started: float,
        outcome: Outcome,
    ) -> AsyncIterator[dict]:
        allowed_doc_ids = await self._document_access_repo.get_allowed_doc_ids(
            user_id=user.id,
            role=user.role,
            department=user.department,
            account_type=user.account_type,
        )
        if not allowed_doc_ids:
            async for event in self._fallback(
                user.id, session_id, started, Outcome.NO_INFO,
                question=question, recent_messages=recent_messages,
            ):
                yield event
            return

        cache_namespace = _rag_cache_namespace(allowed_doc_ids)
        cached = await self._semantic_cache.get(cache_namespace, question)
        if cached:
            answer, sources = cached
            for token in _word_chunks(answer):
                yield {"token": token}
            await self._save_assistant(user.id, session_id, answer, sources, started)
            yield {"done": True, "sources": sources, "session_id": session_id, "cached": True, "outcome": outcome.value}
            return

        results = await self._mcp_client.rag_search(
            query=search_query,
            document_ids=list(allowed_doc_ids),
            top_k=self._settings.rag_result_limit,
        )
        allowed_doc_id_set = set(allowed_doc_ids)
        acl_filtered_results = []
        for result in results:
            if result.document_id not in allowed_doc_id_set:
                logger.warning(
                    "acl_post_filter_violation",
                    extra={
                        "user_id": user.id,
                        "document_id": result.document_id,
                        "chunk_id": result.chunk_id,
                    },
                )
                continue
            acl_filtered_results.append(result)
        if not acl_filtered_results:
            async for event in self._fallback(
                user.id, session_id, started, Outcome.NO_INFO,
                question=question, recent_messages=recent_messages,
            ):
                yield event
            return

        grounded_results = [
            result for result in acl_filtered_results if result.score >= self._settings.rag_score_threshold
        ]
        if not grounded_results:
            async for event in self._fallback(
                user.id, session_id, started, Outcome.NO_INFO,
                question=question, recent_messages=recent_messages,
            ):
                yield event
            return

        sources = [self._source_payload(result) for result in grounded_results]
        context_text = "\n\n".join(
            f"[{index + 1}] {result.document_name} / {result.caption}\n{result.parent_text}"
            for index, result in enumerate(grounded_results)
        )
        answer_parts: list[str] = []
        async for token in _word_stream(
            self._openai_client.stream_answer(
                question=question,
                context=context_text,
                recent_messages=recent_messages,
                sources=grounded_results,
                is_hr_answer=False,
                outcome=Outcome.SUCCESS,
            )
        ):
            answer_parts.append(token)
            yield {"token": token}

        answer = "".join(answer_parts)
        final_sources = [] if _is_fallback_answer(answer) else sources
        if final_sources:
            await self._semantic_cache.put(cache_namespace, question, answer, final_sources)
        await self._save_assistant(user.id, session_id, answer, final_sources, started)
        done_event = {
            "done": True,
            "sources": final_sources,
            "session_id": session_id,
            "outcome": outcome.value,
        }
        if not final_sources:
            done_event["fallback"] = True
        yield done_event

    async def _handle_direct_response(
        self,
        user_id: str,
        session_id: str,
        started: float,
        answer: str,
        outcome: Outcome,
    ) -> AsyncIterator[dict]:
        for token in _word_chunks(answer):
            yield {"token": token}
        await self._save_assistant(user_id, session_id, answer, [], started)
        yield {"done": True, "sources": [], "session_id": session_id, "outcome": outcome.value}

    async def _handle_hr(
        self,
        question: str,
        user: AuthenticatedUser,
        intent: str,
        recent_messages: list[tuple[str, str]],
        session_id: str,
        started: float,
        outcome: Outcome,
    ) -> AsyncIterator[dict]:
        tool_result = await self._mcp_client.hr_query(user_id=user.id, intent=intent)
        context_text = _hr_context_text(tool_result)
        answer_parts: list[str] = []
        async for token in _word_stream(
            self._openai_client.stream_answer(
                question=question,
                context=context_text,
                recent_messages=recent_messages,
                sources=[],
                is_hr_answer=True,
                outcome=Outcome.SUCCESS,
            )
        ):
            answer_parts.append(token)
            yield {"token": token}

        answer = "".join(answer_parts)
        await self._save_assistant(user.id, session_id, answer, [], started)
        yield {"done": True, "sources": [], "session_id": session_id, "outcome": outcome.value}

    async def _handle_generic_tool(
        self,
        tool_name: str,
        arguments: dict,
        user: AuthenticatedUser,
        session_id: str,
        started: float,
        outcome: Outcome,
    ) -> AsyncIterator[dict]:
        """Summary-style handler for any non-rag tool in tool_routing_mode=native.

        Calls call_tool() generically and streams the 'summary' field from the result.
        rag_search always uses _handle_rag (bespoke ACL + score + semantic cache).
        """
        result = await self._mcp_client.call_tool(tool_name, arguments)
        summary = str(result.get("summary") or result.get("answer") or result.get("text") or "")
        if not summary:
            async for event in self._fallback(
                user.id, session_id, started, Outcome.NO_INFO
            ):
                yield event
            return
        for token in _word_chunks(summary):
            yield {"token": token}
        await self._save_assistant(user.id, session_id, summary, [], started)
        yield {"done": True, "sources": [], "session_id": session_id, "outcome": outcome.value}

    async def _fallback(
        self,
        user_id: str,
        session_id: str,
        started: float,
        outcome: Outcome,
        question: str = "",
        recent_messages: list[tuple[str, str]] | None = None,
    ) -> AsyncIterator[dict]:
        messages = {
            Outcome.NO_INFO: "Không tìm thấy thông tin trong tài liệu nội bộ",
            Outcome.REFUSE: "Bạn không có đủ quyền hạn truy cập thông tin này",
            Outcome.CLARIFY: "Tôi chưa hiểu ý bạn, bạn có thể đưa thêm thông tin được không",
            Outcome.OFF_TOPIC: "Câu hỏi của bạn nằm ngoài phạm vi hệ thống HR và tài liệu nội bộ. "
                              "Tôi chỉ hỗ trợ về chính sách công ty, HR và thông tin nội bộ.",
        }
        static_message = messages.get(outcome, "Không tìm thấy thông tin trong tài liệu nội bộ")

        # Neu co conversation context, thu dung LLM de generate tra loi co ngu canh
        if recent_messages and outcome == Outcome.NO_INFO:
            context_lines = "\n".join(
                f"{role}: {content}" for role, content in recent_messages[-6:]
            )
            context_for_llm = (
                f"Lich su cuoi cung:\n{context_lines}\n\n"
                f"Cau hoi hien tai: {question}\n\n"
                f"Tra loi ngan gon, dua tren ngu canh o tren, "
                f"neu cau hoi hien tai la follow-up thi noi ro hon."
            )
            try:
                answer_parts: list[str] = []
                async for token in _word_stream(
                    self._openai_client.stream_answer(
                        question=question,
                        context=context_for_llm,
                        recent_messages=recent_messages,
                        sources=[],
                        is_hr_answer=False,
                        outcome=outcome,
                    )
                ):
                    answer_parts.append(token)
                    yield {"token": token}
                answer = "".join(answer_parts)
                await self._save_assistant(user_id, session_id, answer, [], started)
                yield {"done": True, "sources": [], "session_id": session_id, "fallback": True, "outcome": outcome.value}
                return
            except Exception:
                # LLM failed, fall through to static message
                pass

        for token in _word_chunks(static_message):
            yield {"token": token}
        await self._save_assistant(user_id, session_id, static_message, [], started)
        yield {"done": True, "sources": [], "session_id": session_id, "fallback": True, "outcome": outcome.value}

    async def _save_assistant(
        self,
        user_id: str,
        session_id: str,
        answer: str,
        sources: list[dict],
        started: float,
    ) -> None:
        latency_ms = int((perf_counter() - started) * 1000)
        save_message_detail = getattr(self._conversation_repo, "save_message_detail", None)
        if save_message_detail:
            await save_message_detail(
                user_id=user_id,
                role="assistant",
                content=answer,
                session_id=session_id,
                sources=sources,
                latency_ms=latency_ms,
            )
            context = await self._conversation_repo.get_context(user_id, recent_k=6)
            if (
                self._settings.llm_mode.strip().lower() == "mock"
                and len(context.recent_messages) >= 10
            ):
                summary = _extractive_summary(
                    [(message.role, message.content) for message in context.recent_messages]
                )
                if not summary:
                    return
                await self._conversation_repo.update_summary(user_id, summary)
        else:
            await self._conversation_repo.save_message(user_id, "assistant", answer)

    @staticmethod
    def _source_payload(result: SearchResultLike) -> dict:
        return {
            "document_name": result.document_name,
            "caption": result.caption,
            "heading_path": result.heading_path,
            "score": result.score,
            "source_gcs_uri": result.source_gcs_uri,
        }


def _accumulate_usage(acc: dict, event: Any) -> None:
    """Cộng usage của 1 model call (on_chat_model_end.data.output = AIMessage) vào acc.
    Phủ MỌI lần gọi model (triage/think/answer) -> off-topic vẫn có token triage.
    Best-effort: lỗi/không có usage thì bỏ qua."""
    try:
        out = (event.get("data") or {}).get("output")
        if hasattr(out, "generations"):
            gens = out.generations
            out = gens[0][0].message if gens and gens[0] else out
        um = getattr(out, "usage_metadata", None)
        if not um:
            return
        acc["input"] += int(um.get("input_tokens", 0) or 0)
        acc["output"] += int(um.get("output_tokens", 0) or 0)
        acc["cached"] += int((um.get("input_token_details") or {}).get("cache_read", 0) or 0)
        rm = getattr(out, "response_metadata", None) or {}
        acc["model"] = rm.get("model_name") or acc["model"]
    except Exception:  # noqa: BLE001 — gom usage best-effort
        return


def _usage_from_acc(acc: dict, default_model: str) -> dict | None:
    """Đổi accumulator -> usage_meta cho tracer. None nếu chưa gom được token nào."""
    if acc["input"] == 0 and acc["output"] == 0:
        return None
    return {
        "model": acc["model"] or default_model,
        "input_tokens": acc["input"],
        "output_tokens": acc["output"],
        "cached_tokens": acc["cached"],
    }


def _collect_usage(final_state: Any, default_model: str) -> dict | None:
    """
    Gom token usage từ mọi AIMessage trong final_state (triage + think + answer đều qua
    OpenAIResponsesChatModel) -> {model, input_tokens, output_tokens, cached_tokens}.

    Trả None nếu không có token nào (mock mode / model không trả usage) -> langfuse bỏ
    qua generation. model lấy từ response_metadata.model_name của AIMessage; nhiều model
    khác nhau (vd intent gpt-4o-mini) thì lấy cái cuối cùng có usage.
    """
    messages = final_state.get("messages", []) if isinstance(final_state, dict) else []
    input_tokens = output_tokens = cached_tokens = 0
    model: str | None = None
    for msg in messages:
        usage_metadata = getattr(msg, "usage_metadata", None)
        if not usage_metadata:
            continue
        input_tokens += int(usage_metadata.get("input_tokens", 0) or 0)
        output_tokens += int(usage_metadata.get("output_tokens", 0) or 0)
        details = usage_metadata.get("input_token_details") or {}
        cached_tokens += int(details.get("cache_read", 0) or 0)
        response_metadata = getattr(msg, "response_metadata", None) or {}
        model = response_metadata.get("model_name") or model
    if input_tokens == 0 and output_tokens == 0:
        return None
    return {
        "model": model or default_model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
    }


def _hr_context_text(result: HrQueryResultLike) -> str:
    if result.summary:
        return result.summary
    return f"Khong co du lieu HR phu hop cho intent {result.intent}."


def _extractive_summary(messages: list[tuple[str, str]]) -> str | None:
    snippets = []
    for role, content in messages:
        normalized = " ".join(content.split())
        if not normalized:
            continue
        snippets.append(f"{role}: {normalized[:180]}")
    if not snippets:
        return None
    return "Recent conversation: " + " | ".join(snippets[-6:])


def _word_chunks(text: str) -> list[str]:
    return re.findall(r"\S+\s*", text) or [""]


# Marker prefixes that must never appear in the final answer.
# The LangGraph agent uses native tool_calls for reasoning; if the model still
# emits a text ReAct scaffold this sanitizer strips it before streaming.
_MARKER_RE = re.compile(
    r"^\s*("
    r"THOUGHT|ACTION|OBSERVATION|REASONING|FINAL[\s_]ANSWER"
    r"|Assistant|AI"
    r")[\s:：\-]+.*$",
    re.IGNORECASE | re.MULTILINE,
)


def _strip_agent_markers(text: str) -> str:
    """
    Remove any ReAct-style text markers (THOUGHT:/ACTION:/OBSERVATION: etc.)
    that the model emitted despite being configured for native tool calling.

    Strips entire lines whose leading label matches _MARKER_RE, then collapses
    runs of blank lines to a single blank line and trims surrounding whitespace.
    """
    cleaned = _MARKER_RE.sub("", text)
    # Collapse multiple consecutive blank lines.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


async def _word_stream(chunks: AsyncIterator[str]) -> AsyncIterator[str]:
    buffer = ""
    async for chunk in chunks:
        buffer += chunk
        while True:
            match = re.match(r"(\S+\s+)", buffer)
            if not match:
                break
            token = match.group(1)
            buffer = buffer[len(token) :]
            yield token
    if buffer:
        yield buffer


def _rag_cache_namespace(document_ids: list[str]) -> str:
    joined = "\n".join(sorted(document_ids))
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return f"rag:{digest}"


def _normalize_text(text: str) -> str:
    without_accents = "".join(
        character
        for character in unicodedata.normalize("NFKD", text.lower())
        if not unicodedata.combining(character)
    )
    without_punctuation = re.sub(r"[_\W]+", " ", without_accents, flags=re.UNICODE)
    return re.sub(r"\s+", " ", without_punctuation).strip()


def _is_fallback_answer(answer: str) -> bool:
    """
    Return True when the answer is a generic no-info fallback.

    Matches any phrasing that contains the core "khong tim thay thong tin" substring
    after normalization, covering both old and new prompt wordings.
    """
    normalized = _normalize_text(answer)
    return "khong tim thay thong tin" in normalized


def _extract_tool_call(event: Any) -> dict | None:
    """Rút (name, args) của tool call từ input state của act_node.

    act_node nhận state có messages; AIMessage cuối mang tool_calls. Trả None nếu không
    có tool call (best-effort — mọi lỗi nuốt, KHÔNG làm vỡ stream)."""
    try:
        state = (event.get("data") or {}).get("input")
        messages = state.get("messages") if isinstance(state, dict) else None
        if not messages:
            return None
        last = messages[-1]
        tool_calls = getattr(last, "tool_calls", None)
        if not tool_calls:
            return None
        tc = tool_calls[0]
        if isinstance(tc, dict):
            name, args = tc.get("name"), tc.get("args", {})
        else:
            name, args = getattr(tc, "name", None), getattr(tc, "args", {})
        return {"name": name, "args": args} if name else None
    except Exception:  # noqa: BLE001 — tracing best-effort
        return None


def _msg_brief(msg: Any) -> dict:
    """1 message -> {role, content, [tool_calls]} đọc được trên Langfuse. Cap content để
    tránh payload khổng lồ (system prompt dài)."""
    role = getattr(msg, "type", None) or type(msg).__name__
    content = getattr(msg, "content", msg)
    out: dict[str, Any] = {"role": role, "content": str(content)[:4000]}
    tcs = getattr(msg, "tool_calls", None)
    if tcs:
        out["tool_calls"] = [
            {
                "name": t.get("name") if isinstance(t, dict) else getattr(t, "name", None),
                "args": t.get("args") if isinstance(t, dict) else getattr(t, "args", None),
            }
            for t in tcs
        ]
    return out


def _render_chat_input(event: Any) -> dict:
    """on_chat_model_start.data.input.messages = [[msg, msg, ...]] -> list message phẳng
    = ĐÚNG prompt model nhận. Best-effort."""
    try:
        msgs = ((event.get("data") or {}).get("input") or {}).get("messages") or []
        flat = msgs[0] if msgs and isinstance(msgs[0], (list, tuple)) else msgs
        return {"messages": [_msg_brief(m) for m in flat]}
    except Exception:  # noqa: BLE001
        return {}


def _render_chat_output(event: Any) -> dict:
    """on_chat_model_end.data.output = AIMessage (hoặc LLMResult) -> content + tool_calls
    = model nghĩ/quyết định gì. Best-effort."""
    try:
        out = (event.get("data") or {}).get("output")
        if hasattr(out, "generations"):
            gens = out.generations
            out = gens[0][0].message if gens and gens[0] else out
        return _msg_brief(out)
    except Exception:  # noqa: BLE001
        return {}


def _node_output_summary(output: Any) -> dict:
    """Tóm tắt output của LangGraph node để log vào Langfuse span.
    Bỏ 'messages' (list dài) — chỉ giữ các scalar fields như phase, iteration, outcome.
    """
    if not isinstance(output, dict):
        return {}
    skip = {"messages"}
    return {k: v for k, v in output.items() if k not in skip}
