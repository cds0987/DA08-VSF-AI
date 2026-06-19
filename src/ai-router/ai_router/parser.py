"""Parser chống crash — chuẩn hoá response đa-provider (PLAN §6, §6b).

Đã probe thực tế: content có thể None; reasoning model ngốn token; codex=responses;
OpenAI không trả reasoning text còn OpenRouter (deepseek) có; AGENT cần GIỮ tool_calls.
Quy tắc vàng: KHÔNG bao giờ .strip() trên content khi chưa check None; GIỮ tool_calls.
"""
from __future__ import annotations

from typing import Any

from .schemas import Usage


class RetryWithMoreTokens(Exception):
    """content rỗng vì bị cắt (finish=length) -> caller tăng budget rồi gọi lại."""


def _get(obj: Any, name: str, default=None):
    """Lấy field từ object SDK hoặc dict."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def extract_message(resp: Any) -> Any:
    choices = _get(resp, "choices") or []
    if not choices:
        return None
    return _get(choices[0], "message")


def has_tool_calls(resp: Any) -> bool:
    msg = extract_message(resp)
    return bool(msg and _get(msg, "tool_calls"))


def extract_text(resp: Any) -> str:
    """Lấy text an toàn. AGENT path (có tool_calls) -> caller dùng message thô, KHÔNG gọi đây."""
    choices = _get(resp, "choices") or []
    if not choices:
        return ""
    choice = choices[0]
    msg = _get(choice, "message") or {}
    content = _get(msg, "content")
    if content:
        return content if isinstance(content, str) else str(content)
    # fallback: reasoning (deepseek...) — OpenAI không trả text này
    reasoning = _get(msg, "reasoning") or _get(msg, "reasoning_content")
    if reasoning:
        return reasoning if isinstance(reasoning, str) else str(reasoning)
    refusal = _get(msg, "refusal")
    if refusal:
        return f"[refusal] {refusal}"
    if _get(choice, "finish_reason") == "length":
        raise RetryWithMoreTokens()
    return ""


def extract_usage(resp: Any) -> Usage:
    u = _get(resp, "usage") or {}
    in_tok = int(_get(u, "input_tokens") or _get(u, "prompt_tokens") or 0)
    out_tok = int(_get(u, "output_tokens") or _get(u, "completion_tokens") or 0)
    total = int(_get(u, "total_tokens") or (in_tok + out_tok))
    cost = _get(u, "cost")   # OpenRouter trả USD thật; OpenAI không có
    # reasoning_tokens: OpenAI o-series -> completion_tokens_details.reasoning_tokens;
    # một số provider -> reasoning_tokens phẳng. Đã nằm trong output_tokens (chỉ để observ).
    details = _get(u, "completion_tokens_details") or {}
    reasoning = int(_get(details, "reasoning_tokens") or _get(u, "reasoning_tokens") or 0)
    return Usage(
        input_tokens=in_tok, output_tokens=out_tok, total_tokens=total,
        reasoning_tokens=reasoning,
        cost_usd=float(cost) if cost is not None else None,
    )
