"""Helper gọi chat model trong role — fail mềm (trả None thay vì raise).

Tracing (best-effort): khi caller truyền tracer+trace+node, mỗi LLM call -> 1 generation con
trên Langfuse trace (model, token in/out, cost qua PriceCatalog, router key/tier). Nhờ vậy bấm
vào trace MOSA thấy CÂY BƯỚC: orchestrate -> worker(rag/hr/analyze/leave) -> verify -> answer,
mỗi bước có input/output + token + cost. tracer/trace/node=None -> bỏ qua (no-op an toàn).
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _report_llm(
    tracer: Any, trace: Any, node: str | None, model: Any,
    input_text: str, output_text: str | None,
    usage_metadata: dict | None, router: dict | None, start_dt: datetime,
    first_tok_dt: datetime | None = None, last_tok_dt: datetime | None = None,
    stream_tokens: int = 0,
) -> None:
    """Ghi 1 generation con (per-step) vào trace. Best-effort — lỗi/thiếu tracer -> no-op.

    first_tok_dt = lúc token ĐẦU tiên về (stream) -> Langfuse tính TTFT. inter_token_ms =
    trung bình thời gian giữa các token (TIME-TO-NEXT-TOKEN) -> đo độ mượt streaming mỗi bước.
    """
    if tracer is None or trace is None or node is None:
        return
    try:
        model_name = getattr(model, "model", None) or ""
        timing: dict | None = None
        if first_tok_dt is not None:
            ttft_ms = round((first_tok_dt - start_dt).total_seconds() * 1000, 1)
            inter_ms = None
            if last_tok_dt is not None and stream_tokens > 1:
                inter_ms = round(
                    (last_tok_dt - first_tok_dt).total_seconds() * 1000 / (stream_tokens - 1), 1
                )
            timing = {"ttft_ms": ttft_ms, "inter_token_ms": inter_ms, "stream_tokens": stream_tokens}
        tracer.on_llm(
            trace, node, model_name, input_text, output_text or "",
            usage_metadata, start_dt, datetime.now(timezone.utc), router,
            completion_start_dt=first_tok_dt, timing=timing,
        )
    except Exception as exc:  # noqa: BLE001 — tracing KHÔNG được làm hỏng query
        logger.warning("role_llm_trace_failed: %s", str(exc)[:160])


def _router_of(obj: Any) -> dict | None:
    rm = getattr(obj, "response_metadata", None) or {}
    r = rm.get("router") if isinstance(rm, dict) else None
    return r if isinstance(r, dict) else None


async def acomplete(
    model: Any, system: str, user: str,
    *, tracer: Any = None, trace: Any = None, node: str | None = None,
) -> str | None:
    """Gọi model.ainvoke([System, Human]) -> text. Lỗi/timeout -> None (caller fallback)."""
    if model is None:
        return None
    start_dt = datetime.now(timezone.utc)
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        resp = await model.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
        content = getattr(resp, "content", resp)
        text = str(content).strip() if content else None
        _report_llm(tracer, trace, node, model, user, text,
                    getattr(resp, "usage_metadata", None), _router_of(resp), start_dt)
        return text
    except Exception as exc:  # noqa: BLE001 — worker LLM lỗi KHÔNG được làm hỏng cả câu trả lời
        logger.warning("role_llm_failed: %s", str(exc)[:160])
        return None


async def astream_plan(
    model: Any, system: str, user: str, emit: Any = None, *, node: str = "orchestrate",
    tracer: Any = None, trace: Any = None,
) -> str | None:
    """Cho PLANNER: output = "<prose suy nghĩ>\\n<JSON plan>". STREAM phần PROSE (content TRƯỚC
    dấu '{') ra SSE phase:thought NGAY -> user thấy chữ chạy từ giây đầu (lấp dead-air pha plan),
    rồi NGỪNG emit khi JSON bắt đầu (gom thầm để parse, KHÔNG leak JSON). Cũng surface
    reasoning_content (nếu model nhả). Khác astream_reasoning ở chỗ stream được CẢ content prose
    (không phụ thuộc reasoning ẩn — học từ react non-split). Trả full text (prose+JSON) để parse.

    emit=None / model không astream / lỗi -> fallback acomplete (non-stream an toàn)."""
    if model is None:
        return None
    if emit is None or not hasattr(model, "astream"):
        return await acomplete(model, system, user, tracer=tracer, trace=trace, node=node)
    start_dt = datetime.now(timezone.utc)
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        parts: list[str] = []
        usage_meta: dict | None = None
        router: dict | None = None
        first_tok_dt: datetime | None = None
        last_tok_dt: datetime | None = None
        json_started = False        # content: thấy '{' -> ngừng emit text (JSON plan render thành card)
        async for chunk in model.astream([SystemMessage(content=system), HumanMessage(content=user)]):
            um = getattr(chunk, "usage_metadata", None)
            if um:
                usage_meta = um
            router = router or _router_of(chunk)
            # STREAM HẾT reasoning_content (CoT "đang nghĩ") -> SSE liên tục, KHÔNG freeze. Có lẫn
            # JSON nháp cũng KHÔNG sao (ACL user-id: mỗi user chỉ xem dữ liệu của mình). FE xếp vào
            # mục Orchestrator nên không lộn xộn.
            rtext = (getattr(chunk, "additional_kwargs", None) or {}).get("reasoning_content")
            if rtext:
                # TTFT = token đầu USER THẤY (reasoning stream ngay), không đợi prose/JSON.
                if first_tok_dt is None:
                    first_tok_dt = datetime.now(timezone.utc)
                last_tok_dt = datetime.now(timezone.utc)
                await emit({"phase": "thought", "node": node, "text": rtext})
            tok = getattr(chunk, "content", "") or ""
            if not tok:
                continue
            if first_tok_dt is None:
                first_tok_dt = datetime.now(timezone.utc)
            last_tok_dt = datetime.now(timezone.utc)
            parts.append(tok)
            if json_started:
                continue
            # Phần prose TRƯỚC '{' -> emit thought; tới '{' thì emit phần trước nó rồi dừng.
            idx = tok.find("{")
            if idx == -1:
                if tok.strip():
                    await emit({"phase": "thought", "node": node, "text": tok})
            else:
                json_started = True
                head = tok[:idx]
                if head.strip():
                    await emit({"phase": "thought", "node": node, "text": head})
        text = "".join(parts).strip() or None
        _report_llm(tracer, trace, node, model, user, text, usage_meta, router, start_dt,
                    first_tok_dt, last_tok_dt, len(parts))
        return text
    except Exception as exc:  # noqa: BLE001 — stream lỗi -> non-stream
        logger.warning("role_llm_plan_stream_failed: %s -> acomplete", str(exc)[:160])
        return await acomplete(model, system, user, tracer=tracer, trace=trace, node=node)


async def astream_reasoning(
    model: Any, system: str, user: str, emit: Any = None, *, node: str = "think",
    tracer: Any = None, trace: Any = None,
) -> str | None:
    """Gọi model STREAM nhưng CHỈ surface reasoning_content ra SSE (phase:thought, node) cho
    user thấy model "đang nghĩ" LIVE; content (thường JSON nội bộ: plan/verdict) chỉ GOM để
    caller parse, KHÔNG emit token (tránh lộ JSON ra UI). Trả full content.

    Dùng cho planner (lập kế hoạch) & verify (gate) — vốn cần JSON nhưng pha "nghĩ" lâu, trước
    đây IM LẶNG. emit=None / model không astream / lỗi -> fallback acomplete (non-stream)."""
    if model is None:
        return None
    if emit is None or not hasattr(model, "astream"):
        return await acomplete(model, system, user, tracer=tracer, trace=trace, node=node)
    start_dt = datetime.now(timezone.utc)
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        parts: list[str] = []
        usage_meta: dict | None = None
        router: dict | None = None
        first_tok_dt: datetime | None = None
        last_tok_dt: datetime | None = None
        async for chunk in model.astream([SystemMessage(content=system), HumanMessage(content=user)]):
            um = getattr(chunk, "usage_metadata", None)
            if um:
                usage_meta = um
            router = router or _router_of(chunk)
            rtext = (getattr(chunk, "additional_kwargs", None) or {}).get("reasoning_content")
            if rtext:
                if first_tok_dt is None:   # TTFT = token reasoning đầu (user thấy ngay)
                    first_tok_dt = datetime.now(timezone.utc)
                last_tok_dt = datetime.now(timezone.utc)
                await emit({"phase": "thought", "node": node, "text": rtext})
            tok = getattr(chunk, "content", "") or ""
            if tok:
                if first_tok_dt is None:
                    first_tok_dt = datetime.now(timezone.utc)
                last_tok_dt = datetime.now(timezone.utc)
                parts.append(tok)
        text = "".join(parts).strip() or None
        _report_llm(tracer, trace, node, model, user, text, usage_meta, router, start_dt,
                    first_tok_dt, last_tok_dt, len(parts))
        return text
    except Exception as exc:  # noqa: BLE001 — stream lỗi -> non-stream
        logger.warning("role_llm_reasoning_stream_failed: %s -> acomplete", str(exc)[:160])
        return await acomplete(model, system, user, tracer=tracer, trace=trace, node=node)


async def astream_complete(
    model: Any, system: str, user: str, emit: Any = None, *, node: str = "answer",
    tracer: Any = None, trace: Any = None,
) -> str | None:
    """Như acomplete nhưng STREAM ra SSE. Trả full text (content).

    - content delta  -> emit({token, phase:generating})       # câu trả lời chạy dần
    - reasoning_content -> emit({phase:thought, node, text})   # model "đang nghĩ" hiện LIVE
      (deepseek-reasoner/gpt-5.x lộ reasoning; nếu không có thì thôi). Trước đây BỎ QUA
      reasoning -> model nghĩ lâu mà UI IM LẶNG (user tưởng treo / trả 1 cục). Nay surface ra
      -> user THẤY model hoạt động ngay, rồi câu trả lời stream tiếp.
    emit=None / model không có astream -> fallback acomplete (non-stream)."""
    if model is None:
        return None
    if emit is None or not hasattr(model, "astream"):
        return await acomplete(model, system, user, tracer=tracer, trace=trace, node=node)
    start_dt = datetime.now(timezone.utc)
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        parts: list[str] = []
        usage_meta: dict | None = None
        router: dict | None = None
        first_tok_dt: datetime | None = None
        last_tok_dt: datetime | None = None
        async for chunk in model.astream([SystemMessage(content=system), HumanMessage(content=user)]):
            um = getattr(chunk, "usage_metadata", None)
            if um:
                usage_meta = um
            router = router or _router_of(chunk)
            # answer node: CHỈ stream token câu trả lời (content). KHÔNG đẩy reasoning_content thô
            # (CoT "Soạn trả lời" dài dòng) ra panel suy nghĩ -> khúc agent gọn, không rối.
            tok = getattr(chunk, "content", "") or ""
            if tok:
                if first_tok_dt is None:
                    first_tok_dt = datetime.now(timezone.utc)
                last_tok_dt = datetime.now(timezone.utc)
                parts.append(tok)
                await emit({"token": tok, "phase": "generating"})
        text = "".join(parts).strip()
        _report_llm(tracer, trace, node, model, user, text or None, usage_meta, router, start_dt,
                    first_tok_dt, last_tok_dt, len(parts))
        return text or None
    except Exception as exc:  # noqa: BLE001 — stream lỗi -> thử non-stream
        logger.warning("role_llm_stream_failed: %s -> fallback acomplete", str(exc)[:160])
        return await acomplete(model, system, user, tracer=tracer, trace=trace, node=node)


_VA_SENTINEL = "<<NEED_MORE>>"


def _parse_va(text: str | None) -> tuple[str | None, bool, str]:
    """Parse output verify_answer non-stream -> (answer|None, need_more, missing)."""
    if not text:
        return (None, False, "")
    s = text.strip()
    if s.startswith(_VA_SENTINEL):
        return (None, True, s[len(_VA_SENTINEL):].strip()[:200])
    return (s, False, "")


async def astream_verify_answer(
    model: Any, system: str, user: str, emit: Any = None, *, node: str = "verify",
    allow_replan: bool = True, tracer: Any = None, trace: Any = None,
) -> tuple[str | None, bool, str]:
    """GỘP analyze+verify+answer trong 1 call:
    - reasoning_content -> emit({phase:thought, node}) -> PANEL "Verify — Kiểm tra & tổng hợp"
      hiện model TỔNG HỢP/PHÂN TÍCH live (hết dead-air).
    - content = '<<NEED_MORE>> <thiếu gì>' (cần tra thêm -> replan) HOẶC câu trả lời.
      Khi là answer -> STREAM token ra ({token, phase:generating}) -> câu trả lời chạy dần ở message.
    Trả (answer_text|None, need_more, missing). allow_replan=False -> bỏ qua sentinel (buộc trả lời).
    emit=None / model không astream / lỗi -> fallback acomplete + parse (an toàn)."""
    if model is None:
        return (None, False, "")
    if emit is None or not hasattr(model, "astream"):
        return _parse_va(await acomplete(model, system, user, tracer=tracer, trace=trace, node=node))
    start_dt = datetime.now(timezone.utc)
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        parts: list[str] = []
        usage_meta: dict | None = None
        router: dict | None = None
        first_tok_dt: datetime | None = None
        last_tok_dt: datetime | None = None
        decided: str | None = None   # None (chưa rõ) | 'answer' | 'need_more'
        buf = ""
        async for chunk in model.astream([SystemMessage(content=system), HumanMessage(content=user)]):
            um = getattr(chunk, "usage_metadata", None)
            if um:
                usage_meta = um
            router = router or _router_of(chunk)
            # PANEL: stream suy luận (tổng hợp/phân tích/quyết định) — node=verify giữ mục cũ.
            rtext = (getattr(chunk, "additional_kwargs", None) or {}).get("reasoning_content")
            if rtext:
                # TTFT = token ĐẦU TIÊN USER THẤY (reasoning stream lên panel ngay) — KHÔNG đợi
                # token answer. Trước đây chỉ tính content -> Langfuse báo TTFT cao GIẢ (đã stream
                # reasoning rồi). Tính reasoning -> "Time to first token" phản ánh đúng UX (thấp).
                if first_tok_dt is None:
                    first_tok_dt = datetime.now(timezone.utc)
                last_tok_dt = datetime.now(timezone.utc)
                await emit({"phase": "thought", "node": node, "text": rtext})
            tok = getattr(chunk, "content", "") or ""
            if not tok:
                continue
            if first_tok_dt is None:
                first_tok_dt = datetime.now(timezone.utc)
            last_tok_dt = datetime.now(timezone.utc)
            parts.append(tok)
            if decided == "answer":
                await emit({"token": tok, "phase": "generating"})   # ANSWER stream ở message
                continue
            if decided == "need_more":
                continue                                            # nuốt phần mô tả "thiếu gì"
            # chưa quyết: gom buf tới khi đủ để phân biệt sentinel vs answer
            buf += tok
            stripped = buf.lstrip()
            if not stripped:
                continue
            if len(stripped) < len(_VA_SENTINEL):
                if _VA_SENTINEL.startswith(stripped):
                    continue                                        # còn mơ hồ -> đợi thêm token
                decided = "answer"
                await emit({"token": buf, "phase": "generating"})   # flush phần đã gom
            elif stripped.startswith(_VA_SENTINEL):
                decided = "need_more"
            else:
                decided = "answer"
                await emit({"token": buf, "phase": "generating"})
        full = "".join(parts).strip()
        _report_llm(tracer, trace, node, model, user, full or None, usage_meta, router, start_dt,
                    first_tok_dt, last_tok_dt, len(parts))
        s = full.lstrip()
        if s.startswith(_VA_SENTINEL):
            if allow_replan:
                return (None, True, s[len(_VA_SENTINEL):].strip()[:200])
            return (s[len(_VA_SENTINEL):].strip() or None, False, "")  # hết hạn replan -> coi phần sau là trả lời
        return (full or None, False, "")
    except Exception as exc:  # noqa: BLE001 — stream lỗi -> non-stream
        logger.warning("verify_answer_stream_failed: %s -> acomplete", str(exc)[:160])
        return _parse_va(await acomplete(model, system, user, tracer=tracer, trace=trace, node=node))
