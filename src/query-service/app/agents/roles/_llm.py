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


async def astream_complete(model: Any, system: str, user: str, emit: Any = None) -> str | None:
    """Như acomplete nhưng STREAM token: mỗi delta -> emit({token, phase:generating}) ra SSE.
    Trả full text. emit=None / model không có astream -> fallback acomplete (non-stream)."""
    if model is None:
        return None
    if emit is None or not hasattr(model, "astream"):
        return await acomplete(model, system, user)
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        parts: list[str] = []
        async for chunk in model.astream([SystemMessage(content=system), HumanMessage(content=user)]):
            tok = getattr(chunk, "content", "") or ""
            if tok:
                parts.append(tok)
                await emit({"token": tok, "phase": "generating"})
        text = "".join(parts).strip()
        return text or None
    except Exception as exc:  # noqa: BLE001 — stream lỗi -> thử non-stream
        logger.warning("role_llm_stream_failed: %s -> fallback acomplete", str(exc)[:160])
        return await acomplete(model, system, user)
