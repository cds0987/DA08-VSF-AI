"""NodeLLMAdapter — interface MOSA cho 1 họ model.

Mỗi adapter đóng kín 3 thứ khác nhau giữa các họ model:
  1. transform_params: dựng body request ĐÚNG cho họ model (vd reasoning model BỎ
     temperature/top_p, THÊM reasoning_effort — đã probe thực tế với o3-mini).
  2. parse_usage: chuẩn hoá usage (gồm reasoning_tokens) cho cost/Langfuse.
  3. surfaces_reasoning_stream: provider có stream reasoning_content (deepseek) không.

Adapter là object THUẦN (không giữ client/mạng) -> unit test không cần gọi mạng:
chỉ assert dict params/usage trả ra.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


# reasoning_effort hợp lệ (probe o3-mini: low/medium/high đều OK; None = không gửi).
VALID_REASONING_EFFORT = frozenset({"low", "medium", "high"})


class NodeLLMAdapter(ABC):
    """Chiến lược cắm-tháo cho 1 họ model. Đăng ký bằng @register("name")."""

    #: tên đăng ký trong registry (gán bởi decorator @register)
    name: str = "base"

    # ------------------------------------------------------------------ params
    @abstractmethod
    def transform_params(
        self, params: dict[str, Any], *, reasoning_effort: str | None = None
    ) -> dict[str, Any]:
        """Nhận params base (model/messages/max_completion_tokens/temperature/tools...)
        -> trả params phù hợp họ model này. Phải KHÔNG mutate input (trả dict mới)."""
        raise NotImplementedError

    # ------------------------------------------------------------------- usage
    def parse_usage(self, usage_obj: Any) -> dict[str, Any] | None:
        """usage thô (chat.completions) -> usage_metadata chuẩn LangChain + reasoning_tokens.

        Default phủ cả model thường lẫn reasoning (reasoning_tokens=0 nếu không có) nên
        hầu hết adapter KHÔNG cần override."""
        if usage_obj is None:
            return None
        input_tokens = int(_get(usage_obj, "prompt_tokens", 0) or 0)
        output_tokens = int(_get(usage_obj, "completion_tokens", 0) or 0)
        total = int(_get(usage_obj, "total_tokens", 0) or (input_tokens + output_tokens))

        prompt_details = _get(usage_obj, "prompt_tokens_details", None)
        cached = int(_get(prompt_details, "cached_tokens", 0) or 0) if prompt_details is not None else 0

        completion_details = _get(usage_obj, "completion_tokens_details", None)
        reasoning = (
            int(_get(completion_details, "reasoning_tokens", 0) or 0)
            if completion_details is not None
            else 0
        )
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total,
            "input_token_details": {"cache_read": cached},
            # reasoning_tokens tính như output token -> cần cho cost; 0 với model thường.
            "output_token_details": {"reasoning": reasoning},
        }

    # ------------------------------------------------------------------ stream
    def surfaces_reasoning_stream(self) -> bool:
        """True nếu provider stream reasoning_content riêng (deepseek). OpenAI o-series = False
        (reasoning ẩn) -> UI hiện indicator 'đang suy nghĩ' trong khoảng lặng."""
        return False

    # --------------------------------------------------------------- internals
    @staticmethod
    def _normalise_effort(reasoning_effort: str | None) -> str | None:
        if reasoning_effort is None:
            return None
        eff = str(reasoning_effort).strip().lower()
        return eff if eff in VALID_REASONING_EFFORT else None

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<NodeLLMAdapter {self.name}>"


def _get(obj: Any, name: str, default: Any = None) -> Any:
    """Đọc field từ object SDK hoặc dict (usage có thể là cả hai)."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)
