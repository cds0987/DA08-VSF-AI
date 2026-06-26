"""REGRESSION: embeddings() phải RETRY (không 503 ngay) khi key embed lỗi/cooldown tạm.

Bug (Benchmark 1, 2026-06-25): burst 10 req/s -> embed key OpenRouter 429-rate -> bench 30s ->
pool embed cạn -> resolve None -> 503 "no capacity for embed" -> rag rỗng -> 81% src=0.
Fix: rate-429 cho embed bench NGẮN (EMBED_RATE_COOLDOWN_SECONDS) + embeddings() retry-across-keys
+ backoff (MAX_ATTEMPTS) thay vì single-shot. KHÔNG đổi model (pinned qwen3-4b — giữ vector space).

Dùng asyncio.run (ai-router CI không cài pytest-asyncio) — xem test_chat_stream_regression.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("OPENAI_API_KEY_1", "sk-test-oai")
os.environ.setdefault("OPENROUTER_API_KEY_1", "sk-or-test-1")
os.environ.setdefault("OPENROUTER_API_KEY_2", "sk-or-test-2")
os.environ.pop("AIROUTER_REDIS_URL", None)        # MemoryCounters
os.environ.pop("AIROUTER_INTERNAL_TOKEN", None)

from ai_router.config import get_settings  # noqa: E402
from ai_router.router import (  # noqa: E402
    COOLDOWN_SECONDS,
    RAG_RATE_COOLDOWN_SECONDS,
    RouterCallError,
    Router,
    _embed_backoff,
)


class _Resp:
    def model_dump(self):
        return {
            "data": [{"embedding": [0.1] * 8, "index": 0}],
            "model": "qwen/qwen3-embedding-4b",
            "usage": {"prompt_tokens": 3, "total_tokens": 3},
        }


class _FakeEmbeddings:
    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("upstream 503 transient")
        return _Resp()


class _FakeClient:
    def __init__(self, fail_times: int):
        self.embeddings = _FakeEmbeddings(fail_times)


class _FakeFactory:
    def __init__(self, client):
        self._c = client

    def get(self, base_url, api_key):
        return self._c


def _router(fake):
    r = Router(get_settings())
    r.clients = _FakeFactory(fake)

    # Cô lập retry khỏi state cooldown: no-op error handler -> resolve lại key live ngay.
    async def _noop(*a, **k):
        return None

    r._handle_error = _noop  # type: ignore[assignment]
    return r


def test_embed_backoff_monotonic_and_capped():
    vals = [_embed_backoff(i) for i in range(5)]
    assert vals[0] == 0.5 and vals[1] == 1.0 and vals[2] == 2.0
    assert all(v <= 2.0 for v in vals)              # cap 2s


def test_rag_short_cooldown_constant():
    # embed + rerank bench NGẮN hơn nhiều so với chat (30s) -> pool không cạn dưới burst.
    assert RAG_RATE_COOLDOWN_SECONDS < COOLDOWN_SECONDS
    assert RAG_RATE_COOLDOWN_SECONDS <= 5


def test_embeddings_retries_then_succeeds():
    fake = _FakeClient(fail_times=2)               # 2 lần fail rồi OK
    router = _router(fake)
    data = asyncio.run(router.embeddings({"model": "embed", "input": ["chính sách nghỉ phép"]}))
    assert data.get("data"), "phải trả embedding sau retry (KHÔNG 503)"
    assert fake.embeddings.calls == 3, f"phải retry tới khi OK (got {fake.embeddings.calls})"


def test_embeddings_gives_up_after_max_attempts():
    fake = _FakeClient(fail_times=999)             # luôn fail
    router = _router(fake)
    raised = False
    try:
        asyncio.run(router.embeddings({"model": "embed", "input": ["x"]}))
    except RouterCallError:
        raised = True
    assert raised, "fail mãi -> raise RouterCallError (không treo, không nuốt lỗi)"
    assert fake.embeddings.calls >= 2, "phải thử lại vài lần trước khi bỏ"


class _RecordingEmbeddings:
    """Ghi lại kwargs gửi upstream để soi encoding_format."""
    def __init__(self):
        self.calls = 0
        self.last_kwargs: dict = {}

    async def create(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        return _Resp()


class _RecordingClient:
    def __init__(self):
        self.embeddings = _RecordingEmbeddings()


def test_embeddings_forces_float_encoding_format():
    """REGRESSION (gốc base64-leak): client OpenAI SDK gửi NGẦM encoding_format=base64 ->
    router là hop giữa, gọi upstream base64 TƯỜNG MINH -> SDK không auto-decode -> embedding
    = base64 STR (vi phạm model list[float]) -> dưới tải data méo -> sorted(res.data) TypeError
    -> doc chết. Router PHẢI ép float -> response luôn list[float], contract sạch."""
    fake = _RecordingClient()
    router = _router(fake)
    asyncio.run(router.embeddings(
        {"model": "embed", "input": ["x"], "encoding_format": "base64"}
    ))
    assert fake.embeddings.last_kwargs.get("encoding_format") == "float", (
        f"router phải ÉP encoding_format=float (got "
        f"{fake.embeddings.last_kwargs.get('encoding_format')!r}) — chống base64-leak"
    )


if __name__ == "__main__":
    test_embed_backoff_monotonic_and_capped()
    test_rag_short_cooldown_constant()
    test_embeddings_retries_then_succeeds()
    test_embeddings_gives_up_after_max_attempts()
    test_embeddings_forces_float_encoding_format()
    print("OK")
