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


def _emit_guard(ev: dict) -> dict:
    """Soi event SSE theo hợp đồng (sse_contract) — fail-safe: CHỈ cảnh báo, KHÔNG bao giờ
    làm vỡ câu trả lời. Drift (phase/node lạ, done thiếu field) -> log để biết NGAY ở prod,
    còn gate test chặn từ CI. Trả lại ev nguyên vẹn (chuỗi gọn: yield _emit_guard(ev)).

    Import sse_contract LAZY (trong hàm) — app boot KHÔNG phụ thuộc app.agents (xem
    test_orchestration_does_not_import_agents_at_module_load): agents lỗi -> react vẫn sống."""
    try:
        from app.agents.sse_contract import validate_event
        problems = validate_event(ev)
        if problems:
            logger.warning("sse_contract_violation: %s | event_keys=%s",
                           "; ".join(problems), sorted(ev.keys()))
    except Exception:  # noqa: BLE001 — validate KHÔNG được làm vỡ stream
        pass
    return ev

_ACTIVE_CONVERSATION_ID: ContextVar[str | None] = ContextVar("active_conversation_id", default=None)
_ACTIVE_CONVERSATION_TITLE: ContextVar[str | None] = ContextVar("active_conversation_title", default=None)


# Numeric enum values match the reference REACT agent convention:
#   REFUSE=1, CLARIFY=2, NO_INFO=3, OFF_TOPIC=4, SUCCESS=5
_NO_INFO_FALLBACK = "Mình không tìm thấy thông tin này trong tài liệu nội bộ hiện có."

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


# MOSA path TRƯỚC chỉ trả NO_INFO (rỗng) | SUCCESS (có answer) -> refuse/clarify/no_info đều =SUCCESS
# (bug đo: benchmark auto-grade sai). Phân loại lại từ route + NỘI DUNG answer thật (phản ánh điều
# THỰC SỰ xảy ra: từ chối/hỏi lại/không-thấy/trả lời). Heuristic benchmark-grade (cụm từ templated).
_OFFTOPIC_CUES = ("ngoài phạm vi", "chỉ hỗ trợ", "chỉ có thể hỗ trợ", "không thể hỗ trợ", "nằm ngoài")
_CLARIFY_CUES = ("cho biết cụ thể", "nói rõ", "cụ thể hơn", "chưa rõ", "bạn muốn", "bạn cần", "đưa thêm thông tin")
_NOINFO_CUES = ("không tìm thấy", "chưa tìm được", "chưa lấy được", "không có thông tin", "không tìm được")


def _classify_mosa_outcome(answer: str, route: str) -> int:
    """Suy outcome NGỮ NGHĨA cho MOSA done-event từ answer + route. answer non-empty mặc định SUCCESS.
    no_info cue KHÔNG gate theo sources: no_doc thường RETRIEVE được tài liệu [N] nhưng tài liệu KHÔNG
    chứa đáp án -> vẫn 'không tìm thấy' (có source). Cụm từ templated nên phân biệt tốt cho benchmark."""
    a = (answer or "").lower()
    if any(k in a for k in _OFFTOPIC_CUES):
        return Outcome.OFF_TOPIC.value
    if route == "light" and any(k in a for k in _CLARIFY_CUES):
        return Outcome.CLARIFY.value
    if any(k in a for k in _NOINFO_CUES):
        return Outcome.NO_INFO.value
    return Outcome.SUCCESS.value


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
        langfuse_tracer=None,
        guardrails=None,
        user_access_profile_repo=None,
        access_cache=None,
        summarizer=None,
        title_generator=None,
        agent_mode: str = "react",
        orchestrator_planner=None,
        make_model=None,
        agent_manifest=None,
    ) -> None:
        self._settings = settings
        self._conversation_repo = conversation_repo
        self._document_access_repo = document_access_repo
        self._semantic_cache = semantic_cache
        self._mcp_client = mcp_client
        self._openai_client = openai_client
        self._summarizer = summarizer
        self._title_generator = title_generator
        # Giữ ref task nền (summary update fire-and-forget) -> không bị GC giữa chừng.
        self._bg_tasks: set = set()
        # MOSA Orchestrator-Workers (mode=orchestrator_workers). Mặc định react ->
        # các field này None -> _stream_inner đi path langgraph/legacy cũ KHÔNG đổi.
        self._agent_mode = (agent_mode or "react").strip().lower()
        self._orchestrator_planner = orchestrator_planner
        self._make_model = make_model
        self._agent_manifest = agent_manifest
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
        document_ids: list[str] | None = None,
    ) -> AsyncIterator[dict]:
        """Wrapper mỏng: bọc luồng thật bằng 1 langfuse trace (best-effort, low-level
        client — KHÔNG callback). Tạo trace TRƯỚC _stream_inner để path orchestrator
        có thể tạo child span/generation ngay từ đầu (node plan, rag_retrieve, verify).

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
                _document_ids=document_ids,
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
        _document_ids: list[str] | None = None,
    ) -> AsyncIterator[dict]:
        started = perf_counter()
        # Dùng session_id được truyền từ stream() (đã tạo trước trace) để trace con
        # khớp với trace cha. Legacy path tự sinh mới nếu không có.
        session_id = _session_id or str(uuid4())


        # Input guardrail node ĐÃ BỎ: không còn 1 LLM-judge scan riêng trước graph.
        # Phòng-thủ prompt-injection / off-topic nay GỘP vào think (plan) node — xem mục
        # "== AN TOÀN & CHỐNG THAO TÚNG ==" trong _CLASSIFY_GUIDANCE (prompts.py). think tự nhận
        # diện ý đồ thao túng và xử lý (từ chối nhã nhặn) trong cùng 1 lượt suy luận.
        # Output guardrail (redact PII câu trả lời cuối) VẪN GIỮ ở answer path.

        # NOTE: user question is saved AFTER context is fetched so that
        # state["messages"] contains only prior turns (not the current question).
        # Each path below saves the question right after the context fetch.

        # MOSA Orchestrator-Workers path (mode=orchestrator_workers). Gated CHẶT: chỉ chạy
        # khi planner + make_model có sẵn (dependencies chỉ build khi manifest mode bật).
        # Mặc định react -> bỏ qua hoàn toàn -> path langgraph/legacy cũ.
        if (
            self._agent_mode == "orchestrator_workers"
            and self._orchestrator_planner is not None
            and self._make_model is not None
        ):
            async for event in self._stream_orchestrator(
                question, user, session_id, started, document_ids=_document_ids,
                _lang_trace=_lang_trace,
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

    # NOTE(v2 2026-06-19): path orchestrator-workers stream SSE đầy đủ (router reasoning +
    # plan/step song song + token answer). Force-rebuild marker để CI build image v2 (build
    # 4c6af49 bị gate chặn do e2e flaky; e2e đã fix ở 412ddd8).
    async def _stream_orchestrator(
        self,
        question: str,
        user: AuthenticatedUser,
        session_id: str,
        started: float,
        document_ids: list[str] | None = None,
        _lang_trace: Any = None,
    ) -> AsyncIterator[dict]:
        """MOSA Orchestrator-Workers: router(deepseek-pro) -> workers song song -> synthesize.

        Fail-closed: bất kỳ lỗi nào -> lưu 1 lượt assistant fallback (FE không resend) +
        done NO_INFO. KHÔNG raise ra ngoài. v1 stream câu trả lời theo word-chunk (chưa token
        thật từ synthesize) — đủ cho A/B latency; token-streaming để bước sau.
        """
        from app.agents.base import RoleContext
        from app.agents.graph_builder import build_orchestrator_graph

        # ⏱️ DIAG dead-air: đo timing TỪNG bước pre-plan (chạy TRƯỚC khi span planner được tạo ->
        # Langfuse KHÔNG trace khúc này). Log 1 dòng lúc emit SSE ĐẦU. Tạm để soi nút thắt, bỏ sau.
        import contextlib as _ctxlib
        import time as _time
        _t0 = _time.monotonic()
        _timing: dict[str, float] = {}
        _tracer = self._tracer

        # ⏱️ Child span cho TỪNG bước pre-plan -> Langfuse HIỆN khúc 6-12s "vô hình" (trước span
        # planner) vỡ theo bước trên timeline. Best-effort, lỗi span KHÔNG làm vỡ luồng.
        @_ctxlib.asynccontextmanager
        async def _span(_name: str):
            _sp = _tracer.span_start(_lang_trace, _name) if (_tracer and _lang_trace) else None
            try:
                yield
            finally:
                if _sp is not None:
                    _tracer.span_end(_sp)

        # 🟢 ANTI-DEAD-AIR: phát status NGAY (t≈0) — TRƯỚC pre-plan ~5s -> hết màn hình TRỐNG.
        # Reuse phase/node sẵn trong contract (KHÔNG đổi contract). FE rotate sub-status + hiệu
        # ứng cho wait dài (outlier >25s không bị "đơ" 1 icon).
        yield _emit_guard({"phase": "thinking", "node": "orchestrate",
                           "status": "Đang tiếp nhận & đọc ngữ cảnh…",
                           "session_id": session_id, "agent_mode": "orchestrator_workers"})

        # Context + ACL doc-ids = 2 DB read ĐỘC LẬP -> chạy SONG SONG (gather) thay vì tuần tự
        # (trước: acl nằm trong _run_graph, chạy sau). Giảm round-trip nối tiếp + xếp hàng pool.
        async with _span("preplan.fetch(context_parallel_acl)"):
            ctx_data, _allowed_doc_ids = await asyncio.gather(
                self._get_context(user.id, recent_k=self._settings.rag_top_k),
                self._get_allowed_doc_ids(user),
            )
        _timing["ctx"] = _time.monotonic()
        _timing["acl"] = _timing["ctx"]   # acl chạy SONG SONG với context -> cùng mốc
        recent_messages = [(m.role, m.content) for m in ctx_data.recent_messages]
        try:
            if self._agent_manifest is not None:
                from app.agents.memory import recent_buffer, summary_buffer  # noqa: F401
                from app.agents.registry import MEMORY_REGISTRY

                mem_cfg = self._agent_manifest.memory
                if MEMORY_REGISTRY.has(mem_cfg.impl):
                    provider = MEMORY_REGISTRY.get(mem_cfg.impl)(
                        keep_recent=mem_cfg.keep_recent,
                        summarize_after=mem_cfg.summarize_after,
                        make_model=self._make_model,
                    )
                    recent_messages = await provider.load(recent_messages)
        except Exception as exc:  # noqa: BLE001 — memory lỗi KHÔNG chặn trả lời
            logger.warning("orchestrator_memory_failed: %s", str(exc)[:160])

        # Memory module: dựng MemoryContext (dialogue 7 + summary + task_state + working_set) cho
        # PLANNER -> route follow-up đúng (đa lượt). Reuse recent_messages đã fetch (không double).
        # Fail-safe: lỗi/tắt -> MemoryContext.empty() (degrade, KHÔNG vỡ). load_context CHỈ gọi ở đây
        # (boundary gate). dialogue đầu vào = RAW recent từ repo (memory tự cắt 7 + summary).
        from app.agents.memory.builder import build_memory_client
        from app.agents.memory.contracts import MemoryContext as _MemCtx
        _raw_dialogue = [(m.role, m.content) for m in ctx_data.recent_messages]

        async def _dialogue_loader(_uid: str, _cid: str | None) -> list[tuple[str, str]]:
            return _raw_dialogue

        _mem = build_memory_client(self._settings, dialogue_loader=_dialogue_loader,
                                   make_model=self._make_model)
        _conv_id = _ACTIVE_CONVERSATION_ID.get()
        async with _span("preplan.load_context"):
            mem_ctx = await _mem.load_context(user.id, _conv_id, question) if _mem else _MemCtx.empty()
        _timing["mem"] = _time.monotonic()

        # Status thứ 2 (giữa pre-plan) -> chuỗi biến hoá, không đứng im 1 dòng.
        yield _emit_guard({"phase": "thinking", "node": "plan",
                           "status": "Đang chuẩn bị kế hoạch…",
                           "session_id": session_id, "agent_mode": "orchestrator_workers"})

        # DEFER save_user_message khỏi hot-path (fire-and-forget): bỏ 1 DB write TRƯỚC planner
        # (save 1.4-2.9s dưới burst 150). Lượt sau load mới cần -> ms-fast INSERT chắc chắn xong kịp.
        # Giữ ref tới khi stream xong; lỗi -> log, KHÔNG chặn trả lời.
        def _save_done(_t: asyncio.Task) -> None:
            if not _t.cancelled() and _t.exception() is not None:
                logger.warning("deferred_save_user_message_failed: %s", str(_t.exception())[:160])
        _save_task = asyncio.create_task(self._save_user_message(user.id, question))
        _save_task.add_done_callback(_save_done)
        _timing["save"] = _time.monotonic()

        # Emit channel: node/role đẩy progress (Suy nghĩ / bước tool / token answer) vào queue;
        # ta DRAIN song song với graph.ainvoke -> SSE realtime (thay cho ainvoke "1 cục" trước
        # đây làm mất hết hiệu ứng). Sentinel báo graph xong để dừng drain.
        progress_q: asyncio.Queue = asyncio.Queue()
        _SENTINEL: Any = object()
        streamed_tokens = False
        holder: dict[str, Any] = {}

        async def _emit(ev: dict) -> None:
            await progress_q.put(ev)

        async def _run_graph() -> None:
            try:
                allowed_doc_ids = _allowed_doc_ids   # đã fetch SONG SONG với context (gather ở trên)
                ctx = RoleContext(
                    mcp_client=self._mcp_client,
                    user_id=user.id,
                    allowed_doc_ids=tuple(allowed_doc_ids),
                    hint_doc_ids=tuple(document_ids or []),
                    rag_top_k=self._settings.rag_top_k,
                    rag_score_threshold=self._settings.rag_score_threshold,
                    make_model=self._make_model,
                    emit=_emit,
                    # carry-forward cho leave_action (sửa ngày/loại đơn ở lượt sau).
                    history=tuple(recent_messages),
                    # tracer + trace handle -> role/node ghi generation (model/token/cost) +
                    # span tool mỗi bước vào Langfuse trace (trace MOSA có cây bước, không phẳng).
                    tracer=self._tracer,
                    trace=_lang_trace,
                )
                graph = build_orchestrator_graph(
                    ctx=ctx, manifest=self._agent_manifest,
                    planner=self._orchestrator_planner, make_model=self._make_model,
                )
                _timing["graph"] = _time.monotonic()
                holder["result"] = await graph.ainvoke({
                    "question": question, "user_id": user.id,
                    "allowed_doc_ids": list(allowed_doc_ids),
                    "recent_messages": recent_messages,
                    "memory_context": mem_ctx,   # -> orchestrate node bơm vào PlanContext (planner đa lượt)
                })
            except Exception as exc:  # noqa: BLE001 — fail-closed
                logger.error("orchestrator_stream_failed: %s", str(exc)[:300], exc_info=True)
            finally:
                await progress_q.put(_SENTINEL)

        task = asyncio.create_task(_run_graph())
        _first_logged = False
        while True:
            ev = await progress_q.get()
            if ev is _SENTINEL:
                break
            if not _first_logged:  # ⏱️ DIAG: dòng đầu = bóc tách dead-air theo bước pre-plan
                _first_logged = True
                _g = _timing.get("graph", _t0)
                logger.info(
                    "orchestrator_preplan_timing ctx_ms=%.0f mem_ms=%.0f save_ms=%.0f "
                    "acl_ms=%.0f graph_ms=%.0f plan_first_ms=%.0f TOTAL_first_emit_ms=%.0f",
                    (_timing.get("ctx", _t0) - _t0) * 1000,
                    (_timing.get("mem", _t0) - _timing.get("ctx", _t0)) * 1000,
                    (_timing.get("save", _t0) - _timing.get("mem", _t0)) * 1000,
                    (_timing.get("acl", _t0) - _timing.get("save", _t0)) * 1000,
                    (_g - _timing.get("acl", _t0)) * 1000,
                    (_time.monotonic() - _g) * 1000,
                    (_time.monotonic() - _t0) * 1000,
                )
            if ev.get("token"):
                streamed_tokens = True
            ev.setdefault("agent_mode", "orchestrator_workers")
            ev.setdefault("session_id", session_id)
            yield _emit_guard(ev)
        await task

        result = holder.get("result") or {}
        answer = str(result.get("answer") or "").strip()
        raw_sources = result.get("sources") or []
        # retrieved: tổng chunk rag lấy được (kể cả dưới ngưỡng) — pipeline-health cho smoke.
        retrieved = sum(getattr(o, "retrieved", 0) for o in (result.get("results") or {}).values())

        # Memory WRITE (best-effort, orchestration boundary — worker KHÔNG chạm memory/stateless):
        # ghi working-set (bằng chứng đã lấy -> turn sau không tra lại) + task_state (flow đơn nghỉ dở).
        if _mem is not None:
            try:
                await self._record_memory(_mem, user.id, _conv_id, result)
            except Exception as exc:  # noqa: BLE001 — memory write KHÔNG được làm vỡ trả lời
                logger.warning("memory_record_failed: %s", str(exc)[:160])

        if not answer:
            answer = (
                "Mình chưa lấy được thông tin phù hợp lúc này. Bạn thử lại sau hoặc liên hệ "
                "HR/IT Helpdesk nhé."
            )
            outcome_value = Outcome.NO_INFO.value
            sources: list[dict] = []
        else:
            # Gắn ref [N] cho citation (FE cần), khử trùng theo chunk_id.
            sources, seen, ref = [], set(), 0
            for s in raw_sources:
                cid = s.get("chunk_id")
                if cid in seen:
                    continue
                seen.add(cid)
                ref += 1
                sources.append({**s, "ref": ref})
            # outcome NGỮ NGHĨA (refuse/clarify/no_info/success) thay vì luôn SUCCESS -> benchmark grade đúng.
            _plan_route = getattr(result.get("plan"), "route", "heavy")
            outcome_value = _classify_mosa_outcome(answer, _plan_route)

        answer = await self._output_guardrail.redact(answer)
        # Synth ĐÃ stream token (qua emit) -> KHÔNG word-chunk lại. Chưa stream (light route /
        # fallback / no_info) -> word-chunk câu trả lời cuối để UI vẫn thấy chữ chạy.
        if not streamed_tokens:
            for token in _word_chunks(answer):
                yield _emit_guard({
                    "token": token,
                    "phase": "generating",
                    "agent_mode": "orchestrator_workers",
                    "session_id": session_id,
                })
                await asyncio.sleep(0)

        message_id = await self._save_assistant(user.id, session_id, answer, sources, started, question=question)
        yield _emit_guard({
            "done": True,
            "sources": sources,
            "retrieved": retrieved,  # pipeline-health: chunk lấy được (kể cả <threshold)
            "session_id": session_id,
            "message_id": message_id,
            "outcome": outcome_value,
            "agent_mode": "orchestrator_workers",
            "_answer": answer,
        })

    async def _record_memory(self, mem: Any, user_id: str, conv_id: str | None, result: dict) -> None:
        """Ghi STM sau 1 lượt (orchestration boundary). working-set = bằng chứng đã lấy (rag/hr)
        -> turn sau planner biết, không tra lại. task_state = flow đơn nghỉ dở (clarify=pending,
        form ra=clear). Worker KHÔNG tham gia (stateless) — chỉ đọc OUTPUT của chúng."""
        from app.agents.memory.contracts import TaskState, WorkingSetItem

        plan = result.get("plan")
        results = result.get("results") or {}

        # 1. working-set: digest bằng chứng (rag docs / hr intent)
        for s in getattr(plan, "steps", []) or []:
            out = results.get(s.id)
            if out is None or getattr(out, "status", "") not in ("ok", "no_info"):
                continue
            if s.role == "rag_retrieve":
                docs = sorted({str(src.get("document_name") or "") for src in (out.sources or [])
                               if src.get("document_name")})
                label = str(s.input or s.direction or "")[:80]
                await mem.add_evidence(user_id, conv_id,
                                       WorkingSetItem(kind="rag", label=label, detail={
                                           "docs": docs[:5],
                                           "summary": str(out.output or "")[:400],
                                       }))
            elif s.role == "hr_lookup":
                await mem.add_evidence(user_id, conv_id,
                                       WorkingSetItem(kind="hr", label=str(s.direction or "hồ sơ HR")[:80]))

        # 2. task_state: leave_action -> clarify (pending) hay action JSON (clear).
        leave_out = next((results[k] for k in results if getattr(results[k], "role", "") == "leave_action"), None)
        if leave_out is not None:
            txt = str(getattr(leave_out, "output", "") or "")
            if '"action_type"' in txt:
                await mem.set_task_state(user_id, conv_id, None)  # form đã ra -> phần chat của flow xong
            else:
                await mem.set_task_state(user_id, conv_id,
                                        TaskState(flow="create_leave", missing=("type/reason",), status="pending"))

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
        message_id = await self._save_assistant(user.id, session_id, answer, final_sources, started, question=question)
        done_event = {
            "done": True,
            "sources": final_sources,
            "session_id": session_id,
            "message_id": message_id,
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
        question: str = "",
    ) -> str | None:
        """Trả id row message vừa lưu (nếu có) -> đưa vào done event làm message_id ổn
        định cho FE patch trạng thái action (xem docs/leave-action-state-b2.md)."""
        latency_ms = int((perf_counter() - started) * 1000)
        message_id: str | None = None
        save_message_detail = getattr(self._conversation_repo, "save_message_detail", None)
        if save_message_detail:
            stored = await save_message_detail(
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
            message_id = str(stored.id) if stored is not None else None
            # FIRE-AND-FORGET: gộp summary là memory phụ cho lượt SAU, KHÔNG liên quan câu trả lời
            # hiện tại -> KHÔNG chặn event `done` (trước đây await -> treo ~2-4s/lượt khi hội thoại
            # dài vì 1 LLM call). Chạy nền; giữ ref tránh GC; lỗi -> best-effort (đã try/except trong).
            t = asyncio.create_task(self._maybe_update_summary(user_id))
            self._bg_tasks.add(t)
            t.add_done_callback(self._bg_tasks.discard)
            t2 = asyncio.create_task(self._maybe_auto_title(user_id, question))
            self._bg_tasks.add(t2)
            t2.add_done_callback(self._bg_tasks.discard)
        else:
            await self._conversation_repo.save_message(
                user_id,
                "assistant",
                answer,
                conversation_id=_ACTIVE_CONVERSATION_ID.get(),
            )
        return message_id

    async def _maybe_update_summary(self, user_id: str) -> None:
        """Summary-buffer: gộp các lượt CŨ HƠN window vào `conversations.summary` bằng model
        rẻ. Best-effort (memory phụ — không được làm hỏng lượt). Hội thoại ngắn -> bỏ qua."""
        if not self._settings.summary_enabled or self._summarizer is None:
            return
        try:
            window = max(1, self._settings.agent_recent_k)
            # Lấy rộng hơn window 1 ít để bắt các lượt vừa bị đẩy ra; cũ hơn nữa đã nằm trong summary.
            ctx = await self._get_context(user_id, recent_k=window + 2)
            msgs = ctx.recent_messages
            if len(msgs) <= window * 2:
                return  # chưa vượt window -> chưa có lượt cũ nào để tóm tắt
            evicted = [(m.role, m.content) for m in msgs[: len(msgs) - window * 2]]
            prev = getattr(ctx, "summary", None)
            new_summary = await self._summarizer.summarize(evicted, prev_summary=prev)
            new_summary = (new_summary or "").strip()
            if new_summary and new_summary != (prev or "").strip():
                await self._conversation_repo.update_summary(
                    user_id,
                    new_summary,
                    conversation_id=_ACTIVE_CONVERSATION_ID.get(),
                )
        except Exception:
            logger.warning("summary_update_failed", exc_info=True)

    async def _maybe_auto_title(self, user_id: str, question: str) -> None:
        """Sinh title ngắn cho conversation sau turn 1. Best-effort, fire-and-forget."""
        if not self._settings.title_enabled or self._title_generator is None:
            return
        try:
            conv_id = _ACTIVE_CONVERSATION_ID.get()
            if not conv_id or not question:
                return
            ctx = await self._get_context(user_id, recent_k=5)
            if len(ctx.recent_messages) != 2:
                return  # chỉ chạy đúng turn 1 (1 user + 1 assistant)
            title = await self._title_generator.generate(question)
            if title:
                await self._conversation_repo.update_title(user_id, conv_id, title)
        except Exception:
            logger.warning("auto_title_failed", exc_info=True)

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
    Gom token usage từ mọi AIMessage trong final_state (các node đều qua
    MosaChatModel/OpenAIChatModel) -> {model, input_tokens, output_tokens, cached_tokens}.

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


def _keep_cited_sources(answer: str, sources: list) -> list:
    """Chỉ giữ source có `ref` được LLM cite [N] trong answer.

    - answer cite [1][3] -> giữ source ref 1,3 (bỏ chunk retrieve nhưng không dùng).
    - answer không cite gì (vd "không tìm thấy") -> trả [] -> không show card thừa.
    Ref không khớp source nào (LLM bịa số) tự bị loại vì không có trong sources.
    """
    if not sources:
        return sources
    cited_refs = {int(m) for m in re.findall(r"\[(\d+)\]", answer or "")}
    return [s for s in sources if s.get("ref") in cited_refs]


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
