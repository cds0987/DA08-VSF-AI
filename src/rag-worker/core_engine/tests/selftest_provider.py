"""Self-test AI gateway — chạy OFFLINE (không cần API key):

    python -m core_engine.tests.selftest_provider

Hai phần:
  A. Construct OpenAIProvider THẬT (openai.AsyncOpenAI) với key giả + validate()
     → chứng minh wiring qua OpenAI SDK hợp lệ (client init lazy, KHÔNG gọi mạng).
     Đây là code path thật khi có OPENAI_API_KEY.
  B. End-to-end engine với OfflineProvider qua flow CHUẨN (caption-embed)
     → chứng minh luồng embed→caption→vector-write chạy thật, không phụ thuộc mạng.

Chạy thật: set OPENAI_API_KEY (hoặc EMBED_BASE_URL trỏ vLLM/OpenRouter) rồi
`engine = await build_engine_probe()` — xem README.
"""

from __future__ import annotations

import asyncio
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core_engine import build_engine, IngestInput, OfflineProvider, OpenAIProvider
from core_engine.ai.base import AISettings, CapabilityConfig
from core_engine.caption import ProviderCaptioner

DIM = 256


def _fake_openai_settings() -> AISettings:
    cfg = CapabilityConfig(base_url=None, api_key="sk-test", model="gpt-4o-mini")
    emb = CapabilityConfig(base_url=None, api_key="sk-test", model="text-embedding-3-small")
    return AISettings(embed=emb, caption=cfg, rerank=cfg, embed_dimension=DIM)


async def part_a_construct_real() -> None:
    """Construct OpenAIProvider thật (AsyncOpenAI) + validate — không gọi mạng."""
    provider = OpenAIProvider(_fake_openai_settings())
    provider.validate()                       # config hợp lệ (fail-fast path)
    try:
        # Tạo client thật cho từng capability (lazy, không I/O).
        assert provider._client(provider._s.embed) is not None
        assert provider._client(provider._s.caption) is not None
    except ModuleNotFoundError:
        print("  A. construct OpenAIProvider thật: SKIP (chua cai openai)")
        return
    print("  A. construct OpenAIProvider thật (AsyncOpenAI) + validate: OK (không gọi mạng)")


async def part_b_end_to_end() -> None:
    """Flow chuẩn (caption-embed) qua OfflineProvider."""
    provider = OfflineProvider(DIM)
    engine = build_engine(provider=provider, caption=True)

    # caption qua provider (offline) — không rỗng.
    cap = await ProviderCaptioner(provider).caption("Vào Cài đặt > Bảo mật để đặt lại mật khẩu.")
    assert cap and cap != "(no content)", "caption không được rỗng"

    n = await engine.ingest(IngestInput(
        document_id="d-pw", document_name="Account", file_type="md",
        markdown="# Reset mật khẩu\nVào Cài đặt > Bảo mật để đặt lại mật khẩu, link 15 phút.\n",
    ))
    assert n >= 1, "ingest (caption flow) phải tạo >=1 unit"

    chunk_ids = await engine.vectors.list_chunk_ids_by_document("d-pw")
    assert chunk_ids, "caption flow phải ghi chunk vào vector store"
    print("  B. end-to-end embed→caption→vector-write (offline provider): OK")


async def run() -> None:
    await part_a_construct_real()
    await part_b_end_to_end()
    print("OK - AI gateway self-tests PASS")


if __name__ == "__main__":
    asyncio.run(run())
