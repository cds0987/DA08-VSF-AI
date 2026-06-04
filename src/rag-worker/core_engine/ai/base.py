"""AIProvider — interface MỞ cho mọi outbound AI call (AI gateway, embedding.md §5).

Mọi nơi cần AI (embed · caption · rerank · sau này OCR/query-rewrite) gọi qua
interface này, KHÔNG hardcode SDK trong core (execution-fallback.md §4b). Đổi nhà
cung cấp = viết một `AIProvider` mới + `set_ai_provider`, không sửa nơi gọi.

Hai năng lực tối thiểu, đủ cho toàn pipeline RAG:
- `embed(texts)`  → vector (ingest caption-embed & search query-embed dùng CHUNG
                    provider/model/dimension — search.md §2, embedding.md §0)
- `chat(user)`    → text (caption: ý-nghĩa-nén; rerank: LLM-as-reranker)

`capability` là hint định tuyến (embedding.md §5 per-capability): provider thật
chọn model/endpoint/key theo capability; provider offline chọn dạng phản hồi giả.
Reliability policy (retry+backoff+jitter) đồng nhất cho MỌI AI call (LESSONS §4.9)
— dùng `retry_async` bên dưới.
"""

from __future__ import annotations

import asyncio
import os
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

# Capability hint cho định tuyến per-capability (embedding.md §5).
EMBED = "embed"
CAPTION = "caption"
RERANK = "rerank"
OCR = "ocr"   # image/scanned-doc → text qua vision LLM (đối chiếu haystack LLMDocumentContentExtractor)

# Contract marker GIỮA RERANK_PROMPT (rerank.llm) và OfflineProvider._fake_rerank:
# dòng query trong prompt bắt đầu bằng marker này. Tách hằng dùng chung để prompt
# (nơi sinh) và parser offline (nơi đọc) KHÔNG drift — đổi marker là đổi một chỗ.
RERANK_QUERY_MARKER = "CÂU HỎI:"


# --------------------------------------------------------------------------- #
# Settings — per-capability (base_url · api_key · model), khớp env notebook    #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CapabilityConfig:
    """Cấu hình một capability AI. base_url=None => OpenAI mặc định."""
    base_url: Optional[str]
    api_key: str
    model: str


@dataclass(frozen=True)
class VisionImage:
    """Một ảnh để vision LLM đọc: bytes đã encode base64 + MIME type.

    Adapter (parser) lo phần render ảnh (đọc file / rasterize PDF) — đó là I/O
    xác định, KHÔNG phải AI. Chỉ bước ảnh→text mới đi qua AI gateway (OCR).
    """
    base64_data: str
    mime_type: str


@dataclass(frozen=True)
class AISettings:
    embed: CapabilityConfig
    caption: CapabilityConfig
    rerank: CapabilityConfig
    ocr: Optional[CapabilityConfig] = None   # None => kế thừa cấu hình caption
    embed_dimension: Optional[int] = None   # None => probe từ model (notebook cell 14)
    max_retries: int = 5
    timeout: float = 60.0
    provider: str = "auto"                  # auto | openai | offline

    def cap(self, capability: str) -> CapabilityConfig:
        # OCR dùng chung endpoint/key với caption khi chưa cấu hình riêng (vision model).
        return {
            EMBED: self.embed,
            CAPTION: self.caption,
            RERANK: self.rerank,
            OCR: self.ocr or self.caption,
        }[capability]


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return default


def load_ai_settings() -> AISettings:
    """Đọc env theo quy ước notebook (EMBED_* / CAPTION_* / RERANK_*).

    Key/base-url rỗng được kế thừa theo thứ tự embed → caption → rerank để cấu
    hình một-provider chỉ cần set một bộ. `AI_PROVIDER` ép chế độ (auto mặc định).
    """
    embed_url = os.getenv("EMBED_BASE_URL") or None
    embed_key = _env("EMBED_API_KEY", "OPENAI_API_KEY")
    cap_url = os.getenv("CAPTION_BASE_URL") or embed_url
    cap_key = _env("CAPTION_API_KEY") or embed_key
    rer_url = os.getenv("RERANK_BASE_URL") or cap_url
    rer_key = _env("RERANK_API_KEY") or cap_key
    cap_model = os.getenv("CAPTION_MODEL", "gpt-4o-mini")
    ocr_url = os.getenv("OCR_BASE_URL") or cap_url
    ocr_key = _env("OCR_API_KEY") or cap_key
    dim = os.getenv("EMBED_DIMENSION")
    return AISettings(
        embed=CapabilityConfig(embed_url, embed_key,
                               os.getenv("EMBED_MODEL", "text-embedding-3-small")),
        caption=CapabilityConfig(cap_url, cap_key, cap_model),
        rerank=CapabilityConfig(rer_url, rer_key, os.getenv("RERANK_MODEL", cap_model)),
        # OCR cần vision model — mặc định kế thừa caption (gpt-4o-mini hỗ trợ vision).
        ocr=CapabilityConfig(ocr_url, ocr_key, os.getenv("OCR_MODEL", cap_model)),
        embed_dimension=int(dim) if dim else None,
        provider=os.getenv("AI_PROVIDER", "auto"),
    )


# --------------------------------------------------------------------------- #
# Interface                                                                    #
# --------------------------------------------------------------------------- #
class AIProvider(ABC):
    """Một điểm vào duy nhất cho outbound AI. Stateless về business; chỉ AI I/O."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Tên provider (cho health/log: 'openai' | 'offline')."""

    @abstractmethod
    async def embed(
        self, texts: List[str], *, dimension: Optional[int] = None
    ) -> List[List[float]]:
        """Embed batch, GIỮ NGUYÊN thứ tự. Ingest & query dùng chung hàm này."""

    @abstractmethod
    async def chat(
        self,
        user: str,
        *,
        system: Optional[str] = None,
        capability: str = CAPTION,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Một lượt chat → text. `capability` định tuyến model/endpoint."""

    @abstractmethod
    async def extract_text_from_images(
        self,
        images: List["VisionImage"],
        *,
        prompt: str,
        capability: str = OCR,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Đọc 1+ ảnh (1 tài liệu) → text/markdown qua vision LLM.

        Đây là đường DUY NHẤT cho OCR/vision: parser render ảnh rồi gọi qua đây,
        không tự ôm engine OCR. `capability` định tuyến vision model/endpoint.
        """

    def validate(self) -> None:
        """Config validation fail-fast lúc startup (embedding.md §4). Override nếu cần."""
        return None


# --------------------------------------------------------------------------- #
# Reliability policy đồng nhất cho MỌI AI call (LESSONS §4.9)                   #
# --------------------------------------------------------------------------- #
async def retry_async(fn, *, max_retries: int, base_delay: float = 0.5):
    """Gọi `fn()` (async) với retry + exponential backoff + jitter.

    Dùng chung cho mọi capability để policy AI đồng nhất; backoff tránh đập
    provider khi 429 (embedding.md §7: 429 → tăng backoff, không tăng worker mù).
    """
    attempt = 0
    while True:
        try:
            return await fn()
        except Exception:  # noqa: BLE001 — phân loại transient để ngoài (gateway/DLQ)
            attempt += 1
            if attempt > max_retries:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            await asyncio.sleep(delay + random.uniform(0, base_delay))
