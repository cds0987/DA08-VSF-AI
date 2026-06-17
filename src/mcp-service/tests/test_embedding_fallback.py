"""Test graceful fallback embed: router (base_url) down -> direct OpenAI (key dự phòng).
Bật khi flip embed_base_url -> ai-router để search KHÔNG sập nếu router chết.

Chạy: python -m pytest tests/test_embedding_fallback.py -q
"""
from __future__ import annotations

import asyncio

from app.core.embedding import OpenAIEmbedder, _is_router_down


class _Resp:
    def __init__(self, vec):
        self.data = [type("D", (), {"embedding": vec})()]


class _FakeEmb:
    """Giả AsyncOpenAI: .embeddings.create -> trả result hoặc raise exc."""
    def __init__(self, result=None, exc=None):
        self.embeddings = self
        self._result = result
        self._exc = exc
        self.calls = 0

    async def create(self, **kw):
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return self._result


class _RouterDown(Exception):
    status_code = 503


class _BadRequest(Exception):
    status_code = 400


def _embedder(fallback=False):
    return OpenAIEmbedder(model="m", dimension=3, api_key="k", base_url="http://ai-router",
                          fallback_api_key=("real-oai" if fallback else ""))


def test_is_router_down_classify():
    assert _is_router_down(_RouterDown()) is True       # status 503
    assert _is_router_down(_BadRequest()) is False       # status 400
    assert _is_router_down(ConnectionError("refused")) is True  # tên chứa 'connection'


def test_fallback_on_router_down():
    async def run():
        e = _embedder(fallback=True)
        e._client = _FakeEmb(exc=_RouterDown())
        e._fb_client = _FakeEmb(result=_Resp([0.1, 0.2, 0.3]))
        out = await e.embed("hi")
        assert out == [0.1, 0.2, 0.3]
        assert e._client.calls == 1 and e._fb_client.calls == 1  # primary fail -> fallback
        print("OK fallback khi router down")
    asyncio.run(run())


def test_no_fallback_propagates():
    async def run():
        e = _embedder(fallback=False)         # không cấu hình fallback
        e._client = _FakeEmb(exc=_RouterDown())
        try:
            await e.embed("hi")
            assert False, "phải raise khi không có fallback"
        except _RouterDown:
            print("OK không fallback -> propagate")
    asyncio.run(run())


def test_4xx_not_fallback():
    async def run():
        e = _embedder(fallback=True)
        e._client = _FakeEmb(exc=_BadRequest())
        e._fb_client = _FakeEmb(result=_Resp([9.0]))
        try:
            await e.embed("hi")
            assert False, "4xx là lỗi thật -> KHÔNG fallback"
        except _BadRequest:
            assert e._fb_client.calls == 0
            print("OK 4xx không fallback")
    asyncio.run(run())


if __name__ == "__main__":
    test_is_router_down_classify()
    test_fallback_on_router_down()
    test_no_fallback_propagates()
    test_4xx_not_fallback()
    print("\nALL TESTS PASSED")
