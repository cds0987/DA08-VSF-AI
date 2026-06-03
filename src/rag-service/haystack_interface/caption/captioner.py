"""Caption — sinh ý-nghĩa-nén của section để embed (ingestion.md §6).

Caption khử vocabulary-mismatch giữa câu hỏi tự nhiên và văn phong tài liệu; nó
là thành phần quyết định recall (caption tệ ⇒ search lệch dù full content vẫn
nằm payload). Mọi call AI đi qua AI gateway (provider) → retry/backoff đồng nhất.

Một implementation duy nhất cho cả offline & OpenAI; chế độ do provider quyết định.
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from haystack_interface.ai import AIProvider, CAPTION, get_ai_provider

CAPTION_SYSTEM = (
    "Bạn nén ý nghĩa của một đoạn tài liệu thành 1-2 câu, tập trung vào CHỦ ĐỀ "
    "và CÁC THỰC THỂ/THUẬT NGỮ chính để phục vụ semantic search. "
    "Chỉ trả về câu tóm tắt, không thêm lời dẫn."
)


@runtime_checkable
class Captioner(Protocol):
    async def caption(self, text: str) -> str:
        """Trả caption (ý-nghĩa-nén) của section; không bao giờ rỗng."""
        ...


class ProviderCaptioner:
    """Caption qua AI gateway. Lỗi/caption rỗng → fallback snippet (không để rỗng
    đi embed). Đồng nhất với hành vi notebook."""

    def __init__(self, provider: AIProvider | None = None, *, max_chars: int = 6000):
        self._provider = provider or get_ai_provider()
        self._max_chars = max_chars

    async def caption(self, text: str) -> str:
        src = (text or "").strip()
        try:
            out = await self._provider.chat(
                src[: self._max_chars], system=CAPTION_SYSTEM, capability=CAPTION
            )
        except Exception as e:  # noqa: BLE001 — caption lỗi KHÔNG được làm vỡ ingest
            print("  caption fail -> snippet fallback:", e)
            out = ""
        out = (out or "").strip()
        return out or src[:600] or "(no content)"
