"""Unit test verify_stream: rag-worker là consumer, KHÔNG tự tạo stream.

Khác e2e (cần NATS thật): ở đây inject _js giả để khóa 3 nhánh — stream phủ đủ
subject (ok), stream không tồn tại (raise), stream thiếu subject (raise).
"""

from __future__ import annotations

import types

import pytest

from app.infrastructure.external.nats_client import NatsBroker

pytest.importorskip("nats")
from nats.js.errors import NotFoundError  # noqa: E402


def _broker_with_js(js) -> NatsBroker:
    broker = NatsBroker("nats://unused:4222")
    broker._js = js
    return broker


class _FakeJs:
    def __init__(self, *, subjects=None, not_found=False) -> None:
        self._subjects = subjects
        self._not_found = not_found

    async def stream_info(self, stream):
        if self._not_found:
            raise NotFoundError
        config = types.SimpleNamespace(subjects=list(self._subjects or []))
        return types.SimpleNamespace(config=config)


async def test_verify_stream_ok_when_all_subjects_covered():
    broker = _broker_with_js(_FakeJs(subjects=["doc.ingest", "doc.status"]))
    # Không raise = pass.
    await broker.verify_stream("DOC_EVENTS", ["doc.ingest", "doc.status"])


async def test_verify_stream_raises_when_stream_missing():
    broker = _broker_with_js(_FakeJs(not_found=True))
    with pytest.raises(RuntimeError, match="chưa tồn tại"):
        await broker.verify_stream("DOC_EVENTS", ["doc.ingest"])


async def test_verify_stream_raises_when_subject_missing():
    broker = _broker_with_js(_FakeJs(subjects=["doc.ingest"]))
    with pytest.raises(RuntimeError, match="thiếu subject"):
        await broker.verify_stream("DOC_EVENTS", ["doc.ingest", "doc.status"])
