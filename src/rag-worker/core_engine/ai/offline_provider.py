"""OfflineProvider — AIProvider chạy offline, tất định, KHÔNG mạng/không key.

Dùng cho dev / eval cấu trúc / selftest. Cùng interface với OpenAIProvider nên
chuyển production chỉ là đổi provider ở composition root (factory) — nơi gọi
(embed/caption/rerank) không đổi một dòng.

- `embed`  → hash-embed tất định (text_utils.hash_embed)
- `chat`   → phản hồi giả theo `capability`:
    * caption → snippet ý-nghĩa-nén (heuristic)
    * rerank  → JSON điểm overlap, mô phỏng đúng contract LLM-as-reranker
              (đọc passages `[i] ...` + dòng `CÂU HỎI:` trong prompt)
"""

from __future__ import annotations

import json
import re
from typing import List, Optional

from core_engine.ai.base import (
    AIProvider,
    CAPTION,
    OCR,
    RERANK,
    RERANK_QUERY_MARKER,
    VisionImage,
)
from core_engine.text_utils import hash_embed, overlap_score

DEFAULT_DIM = 256


class OfflineProvider(AIProvider):
    def __init__(self, dimension: int = DEFAULT_DIM):
        self._dim = dimension

    @property
    def name(self) -> str:
        return "offline"

    @property
    def dimension(self) -> int:
        return self._dim

    async def embed(
        self, texts: List[str], *, dimension: Optional[int] = None
    ) -> List[List[float]]:
        return hash_embed(texts, dimension or self._dim)

    async def chat(
        self,
        user: str,
        *,
        system: Optional[str] = None,
        capability: str = CAPTION,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
    ) -> str:
        if capability == RERANK:
            return self._fake_rerank(user)
        # caption (mặc định): ý-nghĩa-nén heuristic = vài từ đầu của section.
        words = (user or "").split()
        return "Tóm tắt: " + " ".join(words[:12]) if words else "(no content)"

    async def extract_text_from_images(
        self,
        images: List[VisionImage],
        *,
        prompt: str,
        capability: str = OCR,
        max_tokens: Optional[int] = None,
    ) -> str:
        # Offline: không có vision model. Trả text tất định, KHÔNG rỗng (để phân
        # biệt với "OCR thất bại"); đủ cho selftest cấu trúc pipeline.
        if not images:
            return ""
        return "\n\n".join(
            f"[offline-ocr page {i + 1} {img.mime_type}]" for i, img in enumerate(images)
        )

    @staticmethod
    def _fake_rerank(prompt: str) -> str:
        """Mô phỏng LLM-as-reranker: chấm overlap query↔passage, trả JSON.

        Bám contract prompt của rerank.llm: dòng query bắt đầu bằng
        `RERANK_QUERY_MARKER` (hằng dùng chung) + các dòng `[i] text`.
        """
        qm = re.search(re.escape(RERANK_QUERY_MARKER) + r"\s*(.*)", prompt)
        query = qm.group(1).strip() if qm else ""
        # Passage `[i] ...` có thể trải NHIỀU dòng (markitdown chèn comment slide,
        # bảng xlsx nhiều hàng...). Chấm trọn passage tới marker `[i+1]` kế tiếp
        # (hoặc hết chuỗi) — LLM thật đọc full content nên stub phải bám theo.
        scores = {
            int(m.group(1)): overlap_score(query, m.group(2))
            for m in re.finditer(r"\[(\d+)\]\s*(.*?)(?=\n\[\d+\]|\Z)", prompt, re.DOTALL)
        }
        return json.dumps(scores)
