"""reasoning_or — adapter cho reasoning model qua OpenRouter (deepseek-reasoner / "pro").

Khác o-series ở chỗ provider STREAM `reasoning_content` riêng (OpenAI ẩn reasoning).
- Bỏ sampling param không hỗ trợ (an toàn cho deepseek-reasoner: bị bỏ qua/ lỗi tuỳ provider).
- KHÔNG gửi reasoning_effort (deepseek-reasoner tự reason, không dùng tham số này).
- surfaces_reasoning_stream()=True -> tầng stream biết tách kênh reasoning vs answer.
"""
from __future__ import annotations

from typing import Any

from ..base import NodeLLMAdapter
from ..registry import register

_UNSUPPORTED = ("temperature", "top_p", "presence_penalty", "frequency_penalty", "logprobs", "top_logprobs")


@register("reasoning_or")
class ReasoningOpenRouterAdapter(NodeLLMAdapter):
    """deepseek-reasoner qua OpenRouter: bỏ sampling param, stream reasoning_content."""

    def transform_params(
        self, params: dict[str, Any], *, reasoning_effort: str | None = None
    ) -> dict[str, Any]:
        out = dict(params)
        for k in _UNSUPPORTED:
            out.pop(k, None)
        # reasoning_effort không áp dụng cho deepseek-reasoner -> loại.
        out.pop("reasoning_effort", None)
        return out

    def surfaces_reasoning_stream(self) -> bool:
        return True
