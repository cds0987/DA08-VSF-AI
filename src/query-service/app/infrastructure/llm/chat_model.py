"""MosaChatModel — BaseChatModel áp adapter MOSA theo node.

Kế thừa OpenAIChatModel (chat.completions, stream, tool, ai-router) và CHỈ thay đổi
2 điểm theo họ model:
  1. _build_params: chèn reasoning_effort rồi cho adapter.transform_params() dọn param
     (vd reasoning model bỏ temperature/top_p).
  2. _usage_metadata: dùng adapter.parse_usage() -> giữ reasoning_tokens cho cost.

bind_tools()/copy() của lớp cha tự bảo toàn subclass + field adapter_name/reasoning_effort.
"""
from __future__ import annotations

from typing import Any, Sequence

from langchain_core.messages import BaseMessage

from app.infrastructure.external.langchain_chat_adapter import OpenAIChatModel
from .base import NodeLLMAdapter
from .loader import get_node_profile
from .registry import get_adapter


class MosaChatModel(OpenAIChatModel):
    """OpenAIChatModel + adapter MOSA (chọn theo node qua profiles.yaml)."""

    adapter_name: str = "standard"
    reasoning_effort: str | None = None

    _adapter_cache: Any = None  # type: ignore[assignment]

    @property
    def adapter(self) -> NodeLLMAdapter:
        if self._adapter_cache is None or self._adapter_cache.name != self.adapter_name:
            self._adapter_cache = get_adapter(self.adapter_name)
        return self._adapter_cache

    # ------------------------------------------------------------------ params
    def _build_params(self, messages: Sequence[BaseMessage]) -> dict:
        params = super()._build_params(messages)
        if self.reasoning_effort:
            params["reasoning_effort"] = self.reasoning_effort
        return self.adapter.transform_params(params, reasoning_effort=self.reasoning_effort)

    # ------------------------------------------------------------------- usage
    def _usage_metadata(self, usage: Any) -> dict | None:  # type: ignore[override]
        # Lớp cha khai báo staticmethod; override instance để định tuyến qua adapter.
        return self.adapter.parse_usage(usage)

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "adapter": self.adapter_name,
            "reasoning_effort": self.reasoning_effort,
        }


def build_node_chat_model(
    node: str,
    *,
    api_key: str,
    base_url: str | None = None,
    timeout: float = 30.0,
    max_output_tokens: int = 2048,
    direct_model: str | None = None,
) -> MosaChatModel:
    """Dựng MosaChatModel cho 1 node theo profiles.yaml.

    - Route qua ai-router (base_url set): field `model` = capability (router map -> model thật).
    - Gọi trực tiếp: model = direct_model, hoặc model đầu trong profile.models, hoặc gpt-4o-mini.
    """
    prof = get_node_profile(node)
    routed = bool(base_url)
    if routed:
        model = prof.capability or node
    else:
        model = direct_model or (prof.models[0] if prof.models else "gpt-4o-mini")
    return MosaChatModel(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=timeout,
        max_output_tokens=max_output_tokens,
        adapter_name=prof.adapter,
        reasoning_effort=prof.reasoning_effort,
    )
