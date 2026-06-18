"""standard — adapter cho model thường (gpt-4o-mini, gpt-5.4-*).

Gửi temperature/top_p bình thường. Đây cũng là FALLBACK an toàn khi profiles.yaml
khai báo adapter không tồn tại (loader tự lùi về 'standard').
"""
from __future__ import annotations

from typing import Any

from ..base import NodeLLMAdapter
from ..registry import register


@register("standard")
class StandardAdapter(NodeLLMAdapter):
    """Model thường: giữ nguyên temperature/top_p, KHÔNG gửi reasoning_effort."""

    def transform_params(
        self, params: dict[str, Any], *, reasoning_effort: str | None = None
    ) -> dict[str, Any]:
        out = dict(params)
        # Model thường không hiểu reasoning_effort -> không bao giờ gửi (tránh 400).
        out.pop("reasoning_effort", None)
        return out
