"""OCR/vision — ảnh & tài liệu scan → markdown qua AI gateway.

Nguyên tắc: MỌI chức năng AI đi qua `core_engine`. OCR là vision LLM nên
nó nằm ở đây, KHÔNG nằm trong parser adapter. Adapter chỉ render ảnh (đọc file /
rasterize PDF — I/O xác định) rồi đưa `VisionImage` cho extractor này.

Cách làm đối chiếu `haystack` upstream (`LLMDocumentContentExtractor`): một prompt
trích xuất + ảnh → vision LLM trả markdown, giữ thứ tự đọc, mô tả bảng/hình. Khác
ở chỗ ta đi qua AIProvider (OpenAI SDK) thay vì component haystack, để giữ một
điểm vào AI duy nhất + retry/backoff đồng nhất.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import List, Protocol, runtime_checkable

from core_engine.ai import AIProvider, OCR, VisionImage, get_ai_provider
from core_engine.logging_utils import Stopwatch, log_event

# Prompt phỏng theo DEFAULT_PROMPT_TEMPLATE của haystack LLMDocumentContentExtractor.
OCR_PROMPT = (
    "You are part of an information extraction pipeline that extracts the content "
    "of image-based documents.\n"
    "Extract the content from the provided image exactly. Format everything as markdown "
    "and retain the reading order of the document.\n"
    "Reproduce tables as markdown tables. For figures/charts you cannot transcribe, "
    "add a short caption describing them.\n"
    "Return only the extracted content, no preamble and no code fences."
)


@runtime_checkable
class ImageTextExtractor(Protocol):
    async def extract(self, images: List[VisionImage]) -> str:
        """Return markdown text recognized from the page images of one document."""


class ProviderImageTextExtractor:
    """OCR qua AIProvider. Một call vision/ảnh (1 trang = 1 ảnh) để giữ ranh giới
    trang + chặn chi phí từng call; nối kết quả theo thứ tự trang.

    Lỗi KHÔNG nuốt (khác caption): OCR fail phải nổi lên để job ingest fail thay vì
    "sống nhưng rỗng" (xem chính sách empty-ingest trong use-case).
    """

    def __init__(self, provider: AIProvider | None = None, *, prompt: str = OCR_PROMPT):
        self._provider = provider or get_ai_provider()
        self._prompt = prompt
        self._logger = logging.getLogger(__name__)
        # Fan-out trang OCR song song (cùng pattern captioner). Throttle THẬT nằm ở
        # AI Router (AIMD/multi-key); semaphore này chỉ chặn 1 doc ôm quá nhiều slot
        # gateway dùng-chung -> tránh ingestion bão hoà, đói chat live. Liên-doc do
        # INGEST_WORKER_COUNT lo; trong-doc do biến này lo.
        self._page_semaphore = asyncio.Semaphore(
            max(1, int(os.getenv("OCR_MAX_CONCURRENCY", "4")))
        )

    async def extract(self, images: List[VisionImage]) -> str:
        if not images:
            return ""
        total_sw = Stopwatch()

        async def _one(index: int, image: VisionImage) -> tuple[int, str, float]:
            async with self._page_semaphore:
                page_sw = Stopwatch()
                text = await self._provider.extract_text_from_images(
                    [image],
                    prompt=self._prompt,
                    capability=OCR,
                )
                return index, (text or "").strip(), page_sw.elapsed_ms()

        # gather giữ NGUYÊN thứ tự theo input + KHÔNG nuốt lỗi (return_exceptions mặc
        # định False) -> 1 trang fail thì cả OCR fail, nổi lên để job ingest fail (đúng
        # chính sách "OCR fail phải surface", khác caption).
        results = await asyncio.gather(*(_one(i, im) for i, im in enumerate(images)))
        pages = [text for _, text, _ in results]
        page_ms = [ms for _, _, ms in results]
        markdown = "\n\n".join(page for page in pages if page).strip()
        total_ms = total_sw.elapsed_ms()
        # Throughput: trang/giây để so cấu hình OCR (model/scale) khi benchmark.
        pages_per_second = round(len(images) / (total_ms / 1000.0), 3) if total_ms else 0.0
        log_event(
            self._logger,
            logging.INFO,
            "ocr_extracted",
            stage="parse",
            page_count=len(images),
            char_count=len(markdown),
            total_ms=total_ms,
            avg_page_ms=round(sum(page_ms) / len(page_ms), 3) if page_ms else 0.0,
            max_page_ms=round(max(page_ms), 3) if page_ms else 0.0,
            pages_per_second=pages_per_second,
        )
        return markdown
