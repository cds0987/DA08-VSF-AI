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
