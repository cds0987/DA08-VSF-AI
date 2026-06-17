"""REGRESSION: chat_stream phải chịu được body có sẵn 'stream' (client OpenAI SDK gửi).

Bug (2026-06-17): client (adapter chat query-service) gửi stream=True trong body ->
router gọi create(stream=True, **body) -> TypeError 'multiple values for stream' -> stream
vỡ -> client nhận rỗng -> answer NO_INFO. Lộ vì đây là client chat.completions streaming
ĐẦU TIÊN đi qua router (trước chỉ Responses API, không qua router). Test này khóa lại.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("OPENAI_API_KEY_1", "sk-test-oai")
os.environ.pop("AIROUTER_REDIS_URL", None)        # MemoryCounters
os.environ.pop("AIROUTER_INTERNAL_TOKEN", None)

import pytest  # noqa: E402

from ai_router.config import get_settings  # noqa: E402
from ai_router.router import Router  # noqa: E402


class _Chunk:
    def model_dump(self):
        return {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


class _FakeCompletions:
    def __init__(self):
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        # Nếu router truyền 'stream' 2 lần, Python ném TypeError TRƯỚC khi tới đây.
        self.calls.append(kwargs)

        async def _gen():
            yield _Chunk()

        return _gen()


class _FakeClient:
    def __init__(self):
        self.chat = type("X", (), {"completions": _FakeCompletions()})()


class _FakeFactory:
    def __init__(self, client):
        self._c = client

    def get(self, base_url, api_key):
        return self._c


@pytest.mark.asyncio
async def test_chat_stream_strips_client_stream_flag():
    router = Router(get_settings())
    fake = _FakeClient()
    router.clients = _FakeFactory(fake)

    body = {
        "model": "answer",
        "messages": [{"role": "user", "content": "chính sách nghỉ phép?"}],
        "stream": True,                              # <-- client SDK gửi (gây bug cũ)
        "stream_options": {"include_usage": True},
    }
    chunks = [c async for c in router.chat_stream("answer", body)]

    assert chunks, "phải yield chunk (stream không vỡ)"
    assert fake.chat.completions.calls, "create phải được gọi (không TypeError)"
    kw = fake.chat.completions.calls[0]
    assert kw.get("stream") is True               # router tự set, đúng 1 lần
    assert "stream" not in {k for k in kw if k != "stream"}  # không nhân đôi
