"""Captioning for section-level semantic indexing."""

from __future__ import annotations

import logging
from typing import Optional, Protocol, runtime_checkable

from haystack_interface.ai import AIProvider, CAPTION, get_ai_provider
from haystack_interface.logging_utils import log_event

CAPTION_SYSTEM = (
    "Ban nen y nghia cua mot doan tai lieu thanh 1-2 cau, tap trung vao chu de "
    "va cac thuc the/thuat ngu chinh de phuc vu semantic search. "
    "Chi tra ve cau tom tat, khong them loi dan."
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
