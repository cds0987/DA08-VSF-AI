import asyncio
from collections.abc import AsyncIterator
from contextvars import ContextVar
from datetime import datetime, timezone
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

_ACTIVE_CONVERSATION_ID: ContextVar[str | None] = ContextVar("active_conversation_id", default=None)
_ACTIVE_CONVERSATION_TITLE: ContextVar[str | None] = ContextVar("active_conversation_title", default=None)


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
        user_access_profile_repo=None,
        access_cache=None,
    ) -> None:
        self._settings = settings
        self._conversation_repo = conversation_repo
        self._document_access_repo = document_access_repo
        self._semantic_cache = semantic_cache
        self._mcp_client = mcp_client
        self._openai_client = openai_client
        self._langgraph_agent = langgraph_agent
        self._tracer = langfuse_tracer
        self._user_access_profile_repo = user_access_profile_repo
        self._access_cache = access_cache
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

    async def _get_allowed_doc_ids(self, user: "AuthenticatedUser") -> list[str]:
        if self._access_cache:
            try:
                cached = await self._access_cache.get(user.id)
                if cached is not None:
                    return cached
            except Exception:
                pass

        profile = None
        if self._user_access_profile_repo:
            try:
                profile = await self._user_access_profile_repo.get_profile(user.id)
            except Exception:
                pass
        effective_department = profile.department if profile else ""
        effective_account_type = profile.account_type if profile else user.account_type

        doc_ids = await self._document_access_repo.get_allowed_doc_ids(
            user_id=user.id,
            role=user.role,
            department=effective_department,
            account_type=effective_account_type,
        )
        if self._access_cache:
            try:
                await self._access_cache.set(user.id, doc_ids)
            except Exception:
                pass
        return doc_ids

    async def _get_effective_department(self, user: "AuthenticatedUser") -> str:
        """Department giờ thuộc HR Service — propagate sang query-service qua
        user_access_profile_repo (populate từ HR events). AuthenticatedUser KHÔNG
        còn mang department (token/`/auth/me` đã bỏ trường này), nên lấy từ profile.
        getattr fallback: an toàn kể cả khi AuthenticatedUser chưa có attr department."""
        if self._user_access_profile_repo:
            try:
                profile = await self._user_access_profile_repo.get_profile(user.id)
                if profile:
                    return profile.department
            except Exception:
                pass
        return getattr(user, "department", "") or ""

    async def stream(
        self,
        question: str,
        user: AuthenticatedUser,
        trace_session: str | None = None,
        conversation_title: str | None = None,
        conversation_id: str | None = None,
    ) -> AsyncIterator[dict]:
        """Wrapper mỏng: bọc luồng thật bằng 1 langfuse trace (best-effort, low-level
        client — KHÔNG callback). Tạo trace TRƯỚC _stream_inner để _stream_langgraph có
        thể tạo child span/generation ngay từ đầu (node triage, think, rag_search).

        trace_session: nếu set (vd "ci-smoke" do smoke CI), dùng làm session_id của TRACE
        thay cho session_id ngẫu nhiên -> gom trace smoke 1 chỗ để deploy kế tự xóa."""
        conversation_token = _ACTIVE_CONVERSATION_ID.set(conversation_id)
        title_token = _ACTIVE_CONVERSATION_TITLE.set(conversation_title)
        tracer = self._tracer
        # Pre-generate session_id để trace có thể tạo trước khi _stream_inner bắt đầu.
        # _stream_inner nhận session_id này thay vì tự sinh uuid4 mới.
        pre_session_id = str(uuid4())
        trace = None
        last_done: dict | None = None
        usage_meta: dict | None = None
        try:
            trace = tracer.start(question, user, trace_session or pre_session_id) if tracer is not None else None
            async for event in self._stream_inner(
                question, user,
                _session_id=pre_session_id,
                _lang_trace=trace,
            ):
                if event.get("done"):
                    # _usage/_answer là kênh nội bộ (token/model/answer cho langfuse) —
                    # pop ra để KHÔNG rò xuống SSE/frontend; chỉ tracer dùng.
                    usage_meta = event.pop("_usage", None)
                    last_done = {**event}  # copy trước khi pop _answer (tracer cần)
                    event.pop("_answer", None)
                    # Đưa trace_id vào done event để frontend dùng khi submit feedback.
                    if tracer is not None and trace is not None:
                        tid = tracer.get_trace_id(trace)
                        if tid:
                            event["trace_id"] = tid
                yield event
        finally:
            try:
                if tracer is not None and trace is not None:
                    tracer.finish(trace, last_done, usage_meta)
            finally:
                _ACTIVE_CONVERSATION_TITLE.reset(title_token)
                _ACTIVE_CONVERSATION_ID.reset(conversation_token)

    async def _stream_inner(
        self,
        question: str,
        user: AuthenticatedUser,
        _session_id: str | None = None,
        _lang_trace: Any = None,
    ) -> AsyncIterator[dict]:
        started = perf_counter()
        # Dùng session_id được truyền từ stream() (đã tạo trước trace) để trace con
        # khớp với trace cha. Legacy path tự sinh mới nếu không có.
        session_id = _session_id or str(uuid4())


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
                question, user, session_id, started, _lang_trace=_lang_trace
            ):
                yield event
            return

        # Legacy path: direct orchestration without agent (mock/test mode)
        context = await self._get_context(user.id, recent_k=5)
        recent_messages = [(message.role, message.content) for message in context.recent_messages]
        await self._save_user_message(user.id, question)
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
        _lang_trace: Any = None,
    ) -> AsyncIterator[dict]:
        """
        Stream responses using the LangGraph agent.
        Uses astream_events for full granularity: token-level SSE + tool lifecycle events.
        Emits events compatible with the reference REACT agent format:
          - token events with phase, agent_mode, session_id, iterations
          - tool events (acting/observing) with phase, agent_mode, session_id, iterations
          - done event with outcome numeric enum, sources, agent_mode, iterations

        _lang_trace: trace handle từ stream() — dùng để tạo child span/generation
        cho langfuse enriched tracing (per-node LLM call + tool call). Best-effort.
        """
        from langchain_core.messages import HumanMessage, AIMessage as LCAIMessage

        allowed_doc_ids = await self._get_allowed_doc_ids(user)
        effective_department = await self._get_effective_department(user)

        # Fetch recent conversation turns for context (follow-up queries like "Ngày mai").
        # IMPORTANT: fetch history BEFORE saving the current question so that
        # state["messages"] contains only prior turns.
        recent_lc_messages: list = []
        try:
            ctx = await self._get_context(user.id, recent_k=4)
            for msg in ctx.recent_messages:
                if msg.role == "user":
                    recent_lc_messages.append(HumanMessage(content=msg.content))
                elif msg.role == "assistant":
                    recent_lc_messages.append(LCAIMessage(content=msg.content))
        except Exception:
            pass  # history is optional — never block the current query

        # Save current question NOW (after the history snapshot is taken).
        await self._save_user_message(user.id, question)

        initial_state = create_initial_state(
            question=question,
            user_id=user.id,
            user_role=user.role,
            user_department=effective_department,
            allowed_doc_ids=list(allowed_doc_ids) if allowed_doc_ids else [],
            session_id=session_id,
            max_iterations=self._settings.agent_max_iterations,
            recent_messages=recent_lc_messages,
            rag_top_k=self._settings.rag_top_k,
            rag_score_threshold=self._settings.rag_score_threshold,
        )

        # Semantic cache — check TRƯỚC astream_events để tránh gọi LLM/tool lãng phí.
        # Namespace = hash(sorted allowed_doc_ids) → user khác permissions = cache khác.
        # Chỉ check khi user có ít nhất 1 doc được phép (cache empty-set namespace vô nghĩa).
        cache_namespace = _rag_cache_namespace(list(allowed_doc_ids) if allowed_doc_ids else [])
        _cache_hit = await self._semantic_cache.get(cache_namespace, question) if allowed_doc_ids else None
        if _cache_hit is not None:
            _ca, _cs = _cache_hit
            for token in _word_chunks(_ca):
                yield {
                    "token": token,
                    "phase": "generating",
                    "agent_mode": "langgraph",
                    "session_id": session_id,
                    "iterations": 0,
                }
                await asyncio.sleep(0)
            await self._save_assistant(user.id, session_id, _ca, _cs, started)
            yield {
                "done": True,
                "sources": _cs,
                "session_id": session_id,
                "outcome": Outcome.SUCCESS.value,
                "agent_mode": "langgraph",
                "iterations": 0,
                "cached": True,
            }
            return

        answer_accumulator: list[str] = []
        # Track which node/name the last iteration was in, to derive a stable iteration count
        last_iteration = 0
        # Track if we already emitted the shortcut acting event
        shortcut_acting_emitted = False
        # Gom usage từ MỌI model call (on_chat_model_end) — gồm cả triage. _collect_usage
        # cũ chỉ đọc final_state["messages"] nên off-topic (triage không vào messages) ra
        # 0 token -> trace $0.00 dù triage vẫn tốn tiền. Accumulator này phủ mọi path.
        _usage_acc: dict[str, Any] = {"input": 0, "output": 0, "cached": 0, "model": None}

        # Langfuse enriched tracing: per run_id accumulate start time + input for LLM
        # calls and tool calls → create child generation/span after each call completes.
        # _lang_trace=None (no tracer or guardrail blocked) → these dicts stay empty.
        _llm_runs: dict[str, dict] = {}   # run_id → {node, start_dt, input_text}
        _tool_runs: dict[str, dict] = {}  # run_id → {name, input_args, start_dt}
        _active_spans: dict[str, Any] = {}  # run_id → span for node lifecycle
        _SPAN_NODES = {"triage", "think", "act", "observe", "answer", "shortcut"}
        _tracer = self._tracer  # LangfuseTracer | None
        # Status text per node — emitted as SSE so the UI can show "AI thinking" indicator
        _NODE_STATUS: dict[str, str] = {
            "triage": "Đang phân tích câu hỏi...",
            "think": "Đang suy nghĩ...",
            "answer": "Đang soạn câu trả lời...",
        }

        # recursion_limit is a defence-in-depth net; Part 1 (force_answer + act→observe→think
        # wiring) provides the logical hard cap.  Set to 3 * max_iterations + overhead.
        # NOTE: langfuse enriched tracing dùng low-level client gọi per event (KHÔNG
        # dùng callback — callback v2 xung đột langchain-core 1.x).
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
                    if node_name in _SPAN_NODES and _lang_trace is not None and _tracer is not None:
                        run_id = event.get("run_id", "")
                        if run_id:
                            span = _tracer.span_start(
                                _lang_trace, name=node_name,
                                input_data={"iteration": last_iteration},
                            )
                            if span is not None:
                                _active_spans[run_id] = span
                    # Emit thinking-status event so the UI shows what the agent is doing
                    node_status = _NODE_STATUS.get(node_name)
                    if node_status:
                        yield {
                            "phase": "thinking",
                            "node": node_name,
                            "status": node_status,
                            "session_id": session_id,
                            "agent_mode": "langgraph",
                            "iterations": last_iteration,
                        }
                    # Emit acting event for act node — use LLM's actual tool decision
                    if node_name == "act":
                        tool_info = _extract_tool_call(event)
                        if tool_info:
                            yield {
                                "phase": "acting",
                                "node": "act",
                                "tool": tool_info["name"],
                                "tool_args": tool_info.get("args", {}),
                                "agent_mode": "langgraph",
                                "session_id": session_id,
                                "iterations": last_iteration,
                            }

                # LLM call started — record start time + input for langfuse enriched trace
                elif event_type == "on_chat_model_start":
                    if _lang_trace is not None and _tracer is not None:
                        run_id = event.get("run_id", "")
                        if run_id:
                            meta = event.get("metadata") or {}
                            node = meta.get("langgraph_node")
                            raw_input = event.get("data", {}).get("input", "")
                            input_text = str(raw_input)[:1000]
                            _llm_runs[run_id] = {
                                "node": node,
                                "start_dt": datetime.now(timezone.utc),
                                "input_text": input_text,
                            }

                # LLM call completed — accumulate usage + create langfuse generation child span
                elif event_type == "on_chat_model_end":
                    # Cộng dồn token của LẦN GỌI NÀY (triage/think/answer) vào rollup.
                    _accumulate_usage(_usage_acc, event)
                    if _lang_trace is not None and _tracer is not None:
                        run_id = event.get("run_id", "")
                        if run_id and run_id in _llm_runs:
                            run_info = _llm_runs.pop(run_id)
                            try:
                                end_dt = datetime.now(timezone.utc)
                                out_msg = event.get("data", {}).get("output")
                                output_text = getattr(out_msg, "content", "") or ""
                                usage_meta_ev = getattr(out_msg, "usage_metadata", None) or {}
                                model_ev = (
                                    (getattr(out_msg, "response_metadata", None) or {}).get("model_name")
                                    or self._settings.openai_llm_model
                                )
                                _tracer.on_llm(
                                    _lang_trace,
                                    node=run_info["node"],
                                    model=model_ev,
                                    input_text=run_info["input_text"],
                                    output_text=output_text[:2000],
                                    usage_metadata=usage_meta_ev,
                                    start_dt=run_info["start_dt"],
                                    end_dt=end_dt,
                                )
                            except Exception:  # noqa: BLE001 — tracing never breaks stream
                                pass

                # Token stream from LLM — filter triage (JSON) to avoid leaking to SSE
                elif event_type == "on_chat_model_stream":
                    node = (event.get("metadata") or {}).get("langgraph_node")
                    if node == "triage":
                        # JSON phân loại nội bộ — KHÔNG đẩy ra SSE/frontend
                        continue
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

                # Tool call started — record start time for langfuse span
                elif event_type == "on_tool_start":
                    tool_name = event["name"]
                    input_data = event.get("data", {}).get("input", {})
                    if _lang_trace is not None and _tracer is not None:
                        run_id = event.get("run_id", "")
                        if run_id:
                            _tool_runs[run_id] = {
                                "name": tool_name,
                                "input_args": input_data,
                                "start_dt": datetime.now(timezone.utc),
                            }
                    _tool_status = (
                        "Đang tìm kiếm tài liệu..."
                        if tool_name == "rag_search"
                        else "Đang truy vấn dữ liệu HR..."
                    )
                    yield {
                        "phase": "acting",
                        "node": "act",
                        "status": _tool_status,
                        "agent_mode": "langgraph",
                        "session_id": session_id,
                        "iterations": last_iteration,
                        "tool": tool_name,
                        "tool_args": input_data,
                    }

                # Tool call completed — create langfuse tool span
                elif event_type == "on_tool_end":
                    tool_name = event["name"]
                    output_data = event.get("data", {}).get("output", "")
                    if _lang_trace is not None and _tracer is not None:
                        run_id = event.get("run_id", "")
                        if run_id and run_id in _tool_runs:
                            tool_info = _tool_runs.pop(run_id)
                            try:
                                _tracer.on_tool(
                                    _lang_trace,
                                    name=tool_info["name"],
                                    input_args=tool_info["input_args"],
                                    output=output_data,
                                    start_dt=tool_info["start_dt"],
                                    end_dt=datetime.now(timezone.utc),
                                )
                            except Exception:  # noqa: BLE001
                                pass
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
                        run_id = event.get("run_id", "")
                        span = _active_spans.pop(run_id, None)
                        if span is not None and _tracer is not None:
                            output = event.get("data", {}).get("output") or {}
                            _tracer.span_end(span, output_data=_node_output_summary(output))
                        # Emit observing event from act node output (ToolMessage with real results)
                        if run_name == "act":
                            out = (event.get("data") or {}).get("output") or {}
                            if isinstance(out, dict):
                                for msg in reversed(out.get("messages") or []):
                                    t_name = getattr(msg, "name", "") or ""
                                    if t_name:
                                        yield {
                                            "phase": "observing",
                                            "tool": t_name,
                                            "tool_result_summary": _parse_tool_result_summary(t_name, msg),
                                            "agent_mode": "langgraph",
                                            "session_id": session_id,
                                            "iterations": last_iteration,
                                        }
                                        break
                        continue

                    final_state = event.get("data", {}).get("output", {})
                    if isinstance(final_state, dict):
                        # Buid Langfuse span(s) for rag_search calls recorded by act_node.
                        # Must run before saving/yielding so spans arrive before trace finishes.
                        if _lang_trace is not None and _tracer is not None:
                            for _rev in final_state.get("rag_search_events") or []:
                                try:
                                    _tracer.on_tool(
                                        _lang_trace,
                                        name="rag_search",
                                        input_args={k: _rev[k] for k in ("query", "top_k", "allowed_count", "threshold") if k in _rev},
                                        output={k: _rev[k] for k in ("total", "qualified", "scores", "doc_names") if k in _rev},
                                        start_dt=datetime.fromisoformat(_rev["start"]),
                                        end_dt=datetime.fromisoformat(_rev["end"]),
                                    )
                                except Exception:  # noqa: BLE001 — tracing never breaks stream
                                    pass

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
                                await asyncio.sleep(0)
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
                                        # Stream the recovered answer word-by-word.
                                        # asyncio.sleep(0) yields control to the event loop so
                                        # each SSE chunk is flushed before the next word is sent —
                                        # without this the tight loop sends all words in one burst.
                                        for token in _word_chunks(clean):
                                            yield {
                                                "token": token,
                                                "phase": "generating",
                                                "agent_mode": "langgraph",
                                                "session_id": session_id,
                                                "iterations": last_iteration,
                                            }
                                            await asyncio.sleep(0)
                                        answer_accumulator.append(clean)
                                        break

                            answer = "".join(answer_accumulator)

                            # If LLM returned nothing at all, emit NO_INFO instead of empty SUCCESS
                            if not answer:
                                shortcut_outcome = "NO_INFO"

                        sources = final_state.get("sources", [])
                        # shortcut path: 0 iterations; think path: iterations = number of act/observe runs
                        final_iteration = 0 if shortcut_response else max(last_iteration, 1)
                        # If think-path but no tool was called → LLM answered from general knowledge → NO_INFO.
                        # hr_query answers have non-empty tool_results → excluded.
                        # rag_search failures already set shortcut_response in act_node → excluded.
                        if not shortcut_response and not sources:
                            if not (final_state.get("tool_results") or []):
                                shortcut_outcome = "NO_INFO"
                        # Override outcome to NO_INFO if the answer is a generic fallback
                        if answer and _is_fallback_answer(answer) and shortcut_outcome == "SUCCESS":
                            shortcut_outcome = "NO_INFO"
                        # Only surface sources for successful answers — if the LLM said "not found"
                        # or is asking a clarifying question, sending sources alongside is misleading.
                        if shortcut_outcome != "SUCCESS" or _is_clarifying_answer(answer):
                            sources = []
                        outcome_value = _outcome_to_enum_value(shortcut_outcome)

                        # Output guardrail — redact PII from final answer before persisting/sending.
                        answer = await self._output_guardrail.redact(answer)

                        await self._save_assistant(user.id, session_id, answer, sources, started)
                        # Cache: chỉ lưu khi SUCCESS + có sources (RAG path), không cache shortcut/HR.
                        if shortcut_outcome == "SUCCESS" and not shortcut_response and sources:
                            await self._semantic_cache.put(cache_namespace, question, answer, sources)
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
        allowed_doc_ids = await self._get_allowed_doc_ids(user)
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

        sources = [self._source_payload(result) for result in acl_filtered_results]
        context_text = "\n\n".join(
            f"[{index + 1}] {result.document_name} / {result.caption}\n{result.parent_text}"
            for index, result in enumerate(acl_filtered_results)
        )
        answer_parts: list[str] = []
        async for token in _word_stream(
            self._openai_client.stream_answer(
                question=question,
                context=context_text,
                recent_messages=recent_messages,
                sources=acl_filtered_results,
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

    async def _get_context(self, user_id: str, recent_k: int):
        return await self._conversation_repo.get_context(
            user_id,
            conversation_id=_ACTIVE_CONVERSATION_ID.get(),
            recent_k=recent_k,
        )

    async def _save_user_message(self, user_id: str, question: str) -> None:
        save_message_detail = getattr(self._conversation_repo, "save_message_detail", None)
        if save_message_detail:
            await save_message_detail(
                user_id=user_id,
                role="user",
                content=question,
                conversation_id=_ACTIVE_CONVERSATION_ID.get(),
                conversation_title=_ACTIVE_CONVERSATION_TITLE.get(),
            )
            return
        await self._conversation_repo.save_message(
            user_id,
            "user",
            question,
            conversation_id=_ACTIVE_CONVERSATION_ID.get(),
        )

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
                conversation_id=_ACTIVE_CONVERSATION_ID.get(),
                conversation_title=_ACTIVE_CONVERSATION_TITLE.get(),
                session_id=session_id,
                sources=sources,
                latency_ms=latency_ms,
                create_if_missing=False,
            )
            context = await self._get_context(user_id, recent_k=6)
            if (
                self._settings.llm_mode.strip().lower() == "mock"
                and len(context.recent_messages) >= 10
            ):
                summary = _extractive_summary(
                    [(message.role, message.content) for message in context.recent_messages]
                )
                if not summary:
                    return
                await self._conversation_repo.update_summary(
                    user_id,
                    summary,
                    conversation_id=_ACTIVE_CONVERSATION_ID.get(),
                )
        else:
            await self._conversation_repo.save_message(
                user_id,
                "assistant",
                answer,
                conversation_id=_ACTIVE_CONVERSATION_ID.get(),
            )

    @staticmethod
    def _source_payload(result: SearchResultLike) -> dict:
        return {
            "document_name": result.document_name,
            "caption": result.caption,
            # snippet = đoạn text literal đã khớp truy vấn -> frontend neo highlight + hiện
            # trích dẫn (caption chỉ là tóm tắt AI, không khớp nguyên văn trong tài liệu).
            "snippet": result.child_text,
            "heading_path": result.heading_path,
            "score": result.score,
            "source_gcs_uri": result.source_gcs_uri,
            "document_id": result.document_id,
            "page_number": result.page_number,
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


def _is_clarifying_answer(answer: str) -> bool:
    """Return True when the LLM's response is a clarifying question rather than a real answer.

    Detects the pattern: LLM found RAG sources but couldn't determine intent, so it asks
    the user to rephrase instead of using the sources. Showing sources alongside a
    clarifying question is misleading — the LLM didn't actually reference them.

    Heuristic: the answer is short, ends with "?", and contains a clarification marker.
    """
    stripped = answer.strip()
    if not stripped.endswith("?"):
        return False
    normalized = _normalize_text(stripped)
    _CLARIFY_MARKERS = ("chua ro", "ban muon hoi gi", "ban co the noi ro", "y ban la", "cu the hon")
    return any(marker in normalized for marker in _CLARIFY_MARKERS)


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


def _parse_tool_result_summary(tool_name: str, msg: Any) -> dict:
    """Parse ToolMessage content → compact summary for SSE observing event."""
    try:
        content = getattr(msg, "content", None) or str(msg)
        if tool_name == "rag_search":
            parsed = json.loads(content) if isinstance(content, str) else content
            results = (parsed or {}).get("results", []) if isinstance(parsed, dict) else []
            docs = list(dict.fromkeys(r.get("document_name", "") for r in results if r.get("document_name")))
            return {"count": len(results), "docs": docs[:4]}
        if tool_name == "hr_query":
            return {"raw": str(content)[:120]}
    except Exception:  # noqa: BLE001 — best-effort
        pass
    return {}


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
