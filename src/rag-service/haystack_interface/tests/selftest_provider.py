"""Self-test AI gateway — chạy OFFLINE (không cần API key):

    python -m haystack_interface.tests.selftest_provider

Hai phần:
  A. Construct OpenAIProvider THẬT (openai.AsyncOpenAI) với key giả + validate()
     → chứng minh wiring qua OpenAI SDK hợp lệ (client init lazy, KHÔNG gọi mạng).
     Đây là code path thật khi có OPENAI_API_KEY.
  B. End-to-end engine với OfflineProvider qua flow CHUẨN (caption-embed +
     LLM-as-reranker) → chứng minh luồng embed→caption→hybrid→rerank chạy thật,
     không phụ thuộc mạng.

Chạy thật: set OPENAI_API_KEY (hoặc EMBED_BASE_URL trỏ vLLM/OpenRouter) rồi
`engine = await build_engine_probe()` — xem README.
"""

from __future__ import annotations

import asyncio
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from haystack_interface import build_engine, IngestInput, OfflineProvider, OpenAIProvider
from haystack_interface.ai.base import AISettings, CapabilityConfig
from haystack_interface.caption import ProviderCaptioner
from haystack_interface.rerank import LLMReranker

DIM = 256


def _fake_openai_settings() -> AISettings:
    cfg = CapabilityConfig(base_url=None, api_key="sk-test", model="gpt-4o-mini")
    emb = CapabilityConfig(base_url=None, api_key="sk-test", model="text-embedding-3-small")
    return AISettings(embed=emb, caption=cfg, rerank=cfg, embed_dimension=DIM)


async def part_a_construct_real() -> None:
    """Construct OpenAIProvider thật (AsyncOpenAI) + validate — không gọi mạng."""
    provider = OpenAIProvider(_fake_openai_settings())
    provider.validate()                       # config hợp lệ (fail-fast path)
    # Tạo client thật cho từng capability (lazy, không I/O).
    assert provider._client(provider._s.embed) is not None
    assert provider._client(provider._s.caption) is not None
    print("  A. construct OpenAIProvider thật (AsyncOpenAI) + validate: OK (không gọi mạng)")


async def part_b_end_to_end() -> None:
    """Flow chuẩn (caption-embed + LLM-rerank) qua OfflineProvider."""
    provider = OfflineProvider(DIM)
    engine = build_engine(provider=provider, caption=True,
                          reranker=LLMReranker(provider))

    # caption qua provider (offline) — không rỗng.
    cap = await ProviderCaptioner(provider).caption("Vào Cài đặt > Bảo mật để đặt lại mật khẩu.")
    assert cap and cap != "(no content)", "caption không được rỗng"

    n = await engine.ingest(IngestInput(
        document_id="d-pw", document_name="Account", file_type="md",
        markdown="# Reset mật khẩu\nVào Cài đặt > Bảo mật để đặt lại mật khẩu, link 15 phút.\n",
    ))
    assert n >= 1, "ingest (caption flow) phải tạo >=1 unit"

    res = await engine.search("reset mật khẩu", rerank_threshold=0.0)
    assert res and res[0].document_id == "d-pw", "search qua LLM-reranker sai top-1"
    assert res[0].rerank_score > 0, "LLM-reranker phải gán rerank_score"
    print("  B. end-to-end embed→caption→hybrid→LLM-rerank (offline provider): OK")


async def run() -> None:
    await part_a_construct_real()
    await part_b_end_to_end()
    print("OK - AI gateway self-tests PASS")


if __name__ == "__main__":
    asyncio.run(run())
