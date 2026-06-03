"""Captioning for section-level semantic indexing."""

from __future__ import annotations

import logging
from typing import Optional, Protocol, runtime_checkable

from haystack_interface.ai import AIProvider, CAPTION, get_ai_provider
from haystack_interface.logging_utils import log_event

CAPTION_SYSTEM = (
    "Bạn nén ý nghĩa của một đoạn tài liệu thành 1-2 câu, tập trung vào CHỦ ĐỀ "
    "và CÁC THỰC THỂ/THUẬT NGỮ chính để phục vụ semantic search. "
    "Chỉ trả về câu tóm tắt, không thêm lời dẫn."
)


@runtime_checkable
class Captioner(Protocol):
    async def caption(self, text: str) -> str:
        """Return a non-empty semantic caption for a section."""


class ProviderCaptioner:
    def __init__(self, provider: AIProvider | None = None, *, max_chars: int = 6000):
        self._provider = provider or get_ai_provider()
        self._max_chars = max_chars
        self._logger = logging.getLogger(__name__)

    async def caption(self, text: str) -> str:
        source_text = (text or "").strip()
        try:
            output = await self._provider.chat(
                source_text[: self._max_chars],
                system=CAPTION_SYSTEM,
                capability=CAPTION,
            )
        except Exception as exc:  # noqa: BLE001
            log_event(
                self._logger,
                logging.WARNING,
                "caption_fallback",
                stage="caption",
                error=str(exc),
            )
            output = ""
        output = (output or "").strip()
        return output or source_text[:600] or "(no content)"
