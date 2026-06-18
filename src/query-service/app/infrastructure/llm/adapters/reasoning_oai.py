"""reasoning_oai — adapter cho reasoning model OpenAI o-series (o3-mini, o4-mini...).

Đã probe thực tế o3-mini (eval/probe_o3mini.py):
  - `temperature` (≠ default) -> 400 "not supported"   => BỎ
  - `top_p` -> 400 "not supported"                       => BỎ
  - `max_tokens` -> 400                                  => dùng max_completion_tokens (caller đã set)
  - `reasoning_effort` low|medium|high -> OK             => GỬI (điều khiển độ sâu/cost)
  - stream content theo token thật; reasoning text bị OpenAI ẩn (không stream)
"""
from __future__ import annotations

from typing import Any

from ..base import NodeLLMAdapter
from ..registry import register

# Param sampling KHÔNG được hỗ trợ bởi o-series -> luôn loại khỏi body.
_UNSUPPORTED = ("temperature", "top_p", "presence_penalty", "frequency_penalty", "logprobs", "top_logprobs")


@register("reasoning_oai")
class ReasoningOpenAIAdapter(NodeLLMAdapter):
    """o-series: bỏ sampling param, thêm reasoning_effort."""

    def transform_params(
        self, params: dict[str, Any], *, reasoning_effort: str | None = None
    ) -> dict[str, Any]:
        out = dict(params)
        for k in _UNSUPPORTED:
            out.pop(k, None)
        eff = self._normalise_effort(reasoning_effort)
        # chat.completions: tools + reasoning_effort KHÔNG được hỗ trợ cho gpt-5.4-mini/o-series
        # (OpenAI 400 -> "use /v1/responses"). Có tools -> BỎ reasoning_effort (model vẫn
        # reason mặc định, chỉ không tinh chỉnh được effort khi gọi tool trên chat API).
        if eff is not None and not out.get("tools"):
            out["reasoning_effort"] = eff
        else:
            out.pop("reasoning_effort", None)
        return out
