"""Helper gọi chat model trong role — fail mềm (trả None thay vì raise)."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def acomplete(model: Any, system: str, user: str) -> str | None:
    """Gọi model.ainvoke([System, Human]) -> text. Lỗi/timeout -> None (caller fallback)."""
    if model is None:
        return None
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        resp = await model.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
        content = getattr(resp, "content", resp)
        return str(content).strip() if content else None
    except Exception as exc:  # noqa: BLE001 — worker LLM lỗi KHÔNG được làm hỏng cả câu trả lời
        logger.warning("role_llm_failed: %s", str(exc)[:160])
        return None


async def astream_reasoning(
    model: Any, system: str, user: str, emit: Any = None, *, node: str = "think",
) -> str | None:
    """Gọi model STREAM nhưng CHỈ surface reasoning_content ra SSE (phase:thought, node) cho
    user thấy model "đang nghĩ" LIVE; content (thường JSON nội bộ: plan/verdict) chỉ GOM để
    caller parse, KHÔNG emit token (tránh lộ JSON ra UI). Trả full content.

    Dùng cho planner (lập kế hoạch) & verify (gate) — vốn cần JSON nhưng pha "nghĩ" lâu, trước
    đây IM LẶNG. emit=None / model không astream / lỗi -> fallback acomplete (non-stream)."""
    if model is None:
        return None
    if emit is None or not hasattr(model, "astream"):
        return await acomplete(model, system, user)
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        parts: list[str] = []
        async for chunk in model.astream([SystemMessage(content=system), HumanMessage(content=user)]):
            rtext = (getattr(chunk, "additional_kwargs", None) or {}).get("reasoning_content")
            if rtext:
                await emit({"phase": "thought", "node": node, "text": rtext})
            tok = getattr(chunk, "content", "") or ""
            if tok:
                parts.append(tok)
        return "".join(parts).strip() or None
    except Exception as exc:  # noqa: BLE001 — stream lỗi -> non-stream
        logger.warning("role_llm_reasoning_stream_failed: %s -> acomplete", str(exc)[:160])
        return await acomplete(model, system, user)


async def astream_complete(
    model: Any, system: str, user: str, emit: Any = None, *, node: str = "answer",
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
        return await acomplete(model, system, user)
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        parts: list[str] = []
        async for chunk in model.astream([SystemMessage(content=system), HumanMessage(content=user)]):
            rtext = (getattr(chunk, "additional_kwargs", None) or {}).get("reasoning_content")
            if rtext:
                await emit({"phase": "thought", "node": node, "text": rtext})
            tok = getattr(chunk, "content", "") or ""
            if tok:
                parts.append(tok)
                await emit({"token": tok, "phase": "generating"})
        text = "".join(parts).strip()
        return text or None
    except Exception as exc:  # noqa: BLE001 — stream lỗi -> thử non-stream
        logger.warning("role_llm_stream_failed: %s -> fallback acomplete", str(exc)[:160])
        return await acomplete(model, system, user)
