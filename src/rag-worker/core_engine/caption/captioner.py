"""Caption — sinh ý-nghĩa-nén của section để embed (ingestion.md §6).

Caption khử vocabulary-mismatch giữa câu hỏi tự nhiên và văn phong tài liệu; nó là
thành phần quyết định recall (caption tệ ⇒ search lệch dù full content vẫn nằm
payload). Mọi call AI đi qua AI gateway (provider) → retry/backoff đồng nhất. Một
implementation duy nhất cho cả offline & OpenAI; chế độ do provider quyết định.
Lỗi/caption rỗng → fallback snippet (log_event WARNING, không để rỗng đi embed).
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import threading
from typing import Optional, Protocol, runtime_checkable

from core_engine.ai import AIProvider, CAPTION, get_ai_provider
from core_engine.logging_utils import log_event

CAPTION_SYSTEM = (
    "Bạn nén ý nghĩa của một đoạn tài liệu thành 1-2 câu, tập trung vào CHỦ ĐỀ "
    "và CÁC THỰC THỂ/THUẬT NGỮ chính để phục vụ semantic search. "
    "Chỉ trả về câu tóm tắt, không thêm lời dẫn."
)


@runtime_checkable
class Captioner(Protocol):
    async def caption(self, text: str) -> str:
        """Return a non-empty semantic caption for a section."""


@dataclass(frozen=True)
class CaptionResult:
    text: str
    used_fallback: bool


class CaptionMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total_calls = 0
        self._fallback_calls = 0

    def record(self, *, used_fallback: bool) -> None:
        with self._lock:
            self._total_calls += 1
            if used_fallback:
                self._fallback_calls += 1

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            total = self._total_calls
            fallback = self._fallback_calls
        rate = float(fallback) / float(total) if total else 0.0
        return {
            "caption_calls_total": float(total),
            "caption_fallback_total": float(fallback),
            "caption_fallback_rate": rate,
        }

    def reset(self) -> None:
        with self._lock:
            self._total_calls = 0
            self._fallback_calls = 0


_METRICS = CaptionMetrics()


def caption_metrics_snapshot() -> dict[str, float]:
    return _METRICS.snapshot()


def reset_caption_metrics() -> None:
    _METRICS.reset()


class ProviderCaptioner:
    def __init__(self, provider: AIProvider | None = None, *, max_chars: int = 6000):
        self._provider = provider or get_ai_provider()
        # Config-driven params đến từ ${VAR} interpolation dưới dạng string -> coerce.
        self._max_chars = int(max_chars)
        self._logger = logging.getLogger(__name__)

    async def caption(self, text: str) -> str:
        return (await self.caption_with_metadata(text)).text

    async def caption_with_metadata(self, text: str) -> CaptionResult:
        source_text = (text or "").strip()
        used_fallback = False
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
            used_fallback = True
        output = (output or "").strip()
        if not output:
            output = source_text[:600] or "(no content)"
            used_fallback = True
        _METRICS.record(used_fallback=used_fallback)
        return CaptionResult(text=output, used_fallback=used_fallback)
