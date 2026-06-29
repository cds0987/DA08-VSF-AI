"""Unit test broker.subscribe retry "already bound".

Durable push-consumer chỉ 1 subscriber active. Deploy restart -> binding cũ chưa nhả
-> "consumer already bound". Phải RETRY (chờ nhả) chứ không raise luôn, nếu không
doc.access delete-cascade dừng hẳn -> orphan vector/artifact tích lũy.
"""

from __future__ import annotations

import pytest

from app.infrastructure.external.nats_client import NatsBroker

pytest.importorskip("nats")


def _broker_with_js(js) -> NatsBroker:
    broker = NatsBroker("nats://unused:4222")
    broker._js = js
    return broker


class _FakeJs:
    """subscribe() raise `exc` cho `fail_times` lần đầu rồi trả sentinel."""

    def __init__(self, *, exc: Exception, fail_times: int, sentinel: object = "SUB") -> None:
        self._exc = exc
        self._fail_times = fail_times
        self._sentinel = sentinel
        self.calls = 0

    async def subscribe(self, subject, *, durable, cb, manual_ack):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._exc
        return self._sentinel


async def _noop_sleep(_seconds):  # tránh chờ thật 2s/nhịp trong test
    return None


async def test_subscribe_retries_until_binding_released(monkeypatch):
    monkeypatch.setattr("app.infrastructure.external.nats_client.asyncio.sleep", _noop_sleep)
    js = _FakeJs(exc=Exception("nats: consumer is already bound to a subscription"), fail_times=2)
    broker = _broker_with_js(js)

    result = await broker.subscribe("doc.access", durable="rag_access", cb=lambda m: None)

    assert result == "SUB"
    assert js.calls == 3  # 2 lần "already bound" + 1 lần thành công


async def test_subscribe_raises_immediately_on_other_error(monkeypatch):
    monkeypatch.setattr("app.infrastructure.external.nats_client.asyncio.sleep", _noop_sleep)
    js = _FakeJs(exc=ValueError("permission denied"), fail_times=99)
    broker = _broker_with_js(js)

    with pytest.raises(ValueError, match="permission denied"):
        await broker.subscribe("doc.access", durable="rag_access", cb=lambda m: None)
    assert js.calls == 1  # KHÔNG retry lỗi khác "already bound"


async def test_subscribe_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr("app.infrastructure.external.nats_client.asyncio.sleep", _noop_sleep)
    js = _FakeJs(exc=Exception("consumer already bound to a subscription"), fail_times=99)
    broker = _broker_with_js(js)

    with pytest.raises(Exception, match="already bound"):
        await broker.subscribe("doc.access", durable="rag_access", cb=lambda m: None)
    assert js.calls == 5  # 5 nhịp rồi bỏ cuộc
