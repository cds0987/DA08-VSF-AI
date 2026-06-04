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
