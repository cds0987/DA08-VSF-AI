"""Guard degraded-response: gateway/provider trả HTTP 200 nhưng body thiếu data/choices
(rate-shed dưới tải) PHẢI thành TransientAIError (retry), KHÔNG để TypeError lọt ra ->
classify_ingest_error xếp permanent -> doc chết không retry (bug 8/100 fail ở load 100-file).
"""
from __future__ import annotations

import pytest

from core_engine.ai import OCR, VisionImage
from core_engine.ai.base import AISettings, CapabilityConfig, TransientAIError
from core_engine.ai.openai_provider import OpenAIProvider


class _Resp:
    def __init__(self, *, data=None, choices=None):
        self.data = data
        self.choices = choices


class _FakeClient:
    """AsyncOpenAI giả: trả về response cố định cho embeddings + chat.completions."""
    def __init__(self, *, embed_resp=None, chat_resp=None):
        async def _embed_create(**kw):
            return embed_resp

        async def _chat_create(**kw):
            return chat_resp

        self.embeddings = type("E", (), {"create": staticmethod(_embed_create)})()
        completions = type("CC", (), {"create": staticmethod(_chat_create)})()
        self.chat = type("C", (), {"completions": completions})()


def _provider(client: _FakeClient) -> tuple[OpenAIProvider, CapabilityConfig]:
    cap = CapabilityConfig("http://ai-router:8010/v1", "tok", "model-x")
    settings = AISettings(embed=cap, caption=cap, ocr=cap, max_retries=1, timeout=5.0)
    provider = OpenAIProvider(settings)
    provider._clients[(cap.base_url, cap.api_key)] = client  # bơm client giả vào pool
    return provider, cap


@pytest.mark.asyncio
async def test_embed_degraded_data_none_raises_transient_not_typeerror() -> None:
    provider, _ = _provider(_FakeClient(embed_resp=_Resp(data=None)))
    with pytest.raises(TransientAIError):
        await provider.embed(["hello"])


@pytest.mark.asyncio
async def test_embed_degraded_length_mismatch_raises_transient() -> None:
    # 1 vector cho 2 input -> map index sai -> transient (retry), không trả bừa.
    one = _Resp(data=[type("D", (), {"index": 0, "embedding": [0.1]})()])
    provider, _ = _provider(_FakeClient(embed_resp=one))
    with pytest.raises(TransientAIError):
        await provider.embed(["a", "b"])


@pytest.mark.asyncio
async def test_ocr_degraded_choices_none_raises_transient() -> None:
    provider, _ = _provider(_FakeClient(chat_resp=_Resp(choices=None)))
    with pytest.raises(TransientAIError):
        await provider.extract_text_from_images(
            [VisionImage(base64_data="QQ==", mime_type="image/png")],
            prompt="x", capability=OCR,
        )
