from __future__ import annotations

import pytest

from core_engine.ai import OCR, VisionImage
from core_engine.ai.offline_provider import OfflineProvider
from core_engine.ocr import ProviderImageTextExtractor


@pytest.mark.asyncio
async def test_provider_image_text_extractor_uses_gateway_per_page() -> None:
    extractor = ProviderImageTextExtractor(OfflineProvider(256))
    images = [
        VisionImage(base64_data="QQ==", mime_type="image/png"),
        VisionImage(base64_data="Qg==", mime_type="image/png"),
    ]

    markdown = await extractor.extract(images)

    # Extractor gọi gateway 1-call-mỗi-trang rồi nối; 2 ảnh ⇒ 2 khối stub.
    assert markdown.count("offline-ocr") == 2


@pytest.mark.asyncio
async def test_provider_image_text_extractor_empty_input_returns_empty() -> None:
    extractor = ProviderImageTextExtractor(OfflineProvider(256))
    assert await extractor.extract([]) == ""


@pytest.mark.asyncio
async def test_ocr_preserves_page_order_when_concurrent() -> None:
    """Fan-out song song nhưng markdown PHẢI theo đúng thứ tự trang (trang sau xong
    trước không được nhảy lên đầu)."""
    import asyncio

    class OutOfOrderProvider(OfflineProvider):
        async def extract_text_from_images(self, images, *, prompt, capability=OCR, max_tokens=None):
            # ảnh đầu (data 'A') chậm hơn ảnh sau ('B') -> hoàn tất ngược thứ tự
            data = images[0].base64_data
            await asyncio.sleep(0.02 if data == "QQ==" else 0.0)
            return f"PAGE-{data}"

    extractor = ProviderImageTextExtractor(OutOfOrderProvider(256))
    images = [
        VisionImage(base64_data="QQ==", mime_type="image/png"),  # trang 0 (chậm)
        VisionImage(base64_data="Qg==", mime_type="image/png"),  # trang 1 (nhanh)
    ]
    markdown = await extractor.extract(images)
    assert markdown == "PAGE-QQ==\n\nPAGE-Qg=="


@pytest.mark.asyncio
async def test_ocr_error_propagates_not_swallowed() -> None:
    """1 trang lỗi -> cả OCR raise (không nuốt) để job ingest fail đúng chính sách."""

    class FailingProvider(OfflineProvider):
        async def extract_text_from_images(self, images, *, prompt, capability=OCR, max_tokens=None):
            raise RuntimeError("vision boom")

    extractor = ProviderImageTextExtractor(FailingProvider(256))
    with pytest.raises(RuntimeError):
        await extractor.extract([VisionImage(base64_data="QQ==", mime_type="image/png")])


@pytest.mark.asyncio
async def test_ocr_routes_through_provider_capability() -> None:
    """OCR phải đi qua AIProvider.extract_text_from_images với capability=ocr."""

    seen: dict = {}

    class RecordingProvider(OfflineProvider):
        async def extract_text_from_images(self, images, *, prompt, capability=OCR, max_tokens=None):
            seen["capability"] = capability
            seen["prompt"] = prompt
            return "ok"

    extractor = ProviderImageTextExtractor(RecordingProvider(256))
    await extractor.extract([VisionImage(base64_data="QQ==", mime_type="image/png")])

    assert seen["capability"] == OCR
    assert "markdown" in seen["prompt"].lower()
