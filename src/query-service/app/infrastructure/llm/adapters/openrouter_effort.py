"""openrouter_effort — chỉnh "ĐỘ NGHĨ" của reasoning model qua OpenRouter.

deepseek-v4-flash/pro REASON theo nhu cầu: việc khó (lập kế hoạch decompose) -> nó nghĩ rất
nhiều token -> CHẬM (đo thực tế: plan mất 44s vì nghĩ ~2200 token). OpenRouter cho cắt độ nghĩ
qua field `reasoning: {effort: low|medium|high}` (gửi trong EXTRA_BODY -> openai SDK forward vào
body -> ai-router chuyển tiếp). effort=low -> reason ít -> plan NHANH (~5s) mà vẫn đủ chất.

Khác standard: standard BỎ reasoning_effort (model thường); ở đây DỊCH reasoning_effort thành
nested `reasoning:{effort}` cho OpenRouter. Khác reasoning_or: reasoning_or để model tự reason
(không cắt); ở đây CHỦ ĐỘNG cắt độ nghĩ per-node (qua profiles.yaml -> hot-config).
"""
from __future__ import annotations

from typing import Any

from ..base import NodeLLMAdapter
from ..registry import register

# deepseek qua OpenRouter KHÔNG nhận sampling param -> loại để tránh lỗi/bị bỏ qua.
_UNSUPPORTED = ("temperature", "top_p", "presence_penalty", "frequency_penalty", "logprobs", "top_logprobs")


@register("openrouter_effort")
class OpenRouterEffortAdapter(NodeLLMAdapter):
    """deepseek (OpenRouter): cắt độ nghĩ qua reasoning:{effort} trong extra_body."""

    def transform_params(
        self, params: dict[str, Any], *, reasoning_effort: str | None = None
    ) -> dict[str, Any]:
        out = dict(params)
        for k in _UNSUPPORTED:
            out.pop(k, None)
        # OpenRouter dùng NESTED 'reasoning', KHÔNG phải top-level 'reasoning_effort' (đó là OpenAI
        # o-series). Loại reasoning_effort top-level rồi gắn vào extra_body để forward đúng.
        out.pop("reasoning_effort", None)
        re_str = str(reasoning_effort or "").strip().lower()
        if re_str in ("off", "none", "disabled", "false", "no"):
            # TẮT HẲN reasoning -> model nhồi answer vào CONTENT (không vào reasoning_content).
            # Bắt buộc cho //hóa answer: nhiều model (qwen/glm/llama/hy3) là reasoning-model -> nếu
            # để reasoning ON thì answer rớt vào reasoning_content, content RỖNG -> verify dump raw.
            # deepseek reasoning-off cũng ra 'BƯỚC' trong content -> đồng nhất (soft-adapter _va_split).
            extra = dict(out.get("extra_body") or {})
            extra["reasoning"] = {"enabled": False}
            out["extra_body"] = extra
            return out
        eff = self._normalise_effort(reasoning_effort)
        if eff is not None:
            extra = dict(out.get("extra_body") or {})
            extra["reasoning"] = {"effort": eff}
            out["extra_body"] = extra
        return out

    def surfaces_reasoning_stream(self) -> bool:
        return True
