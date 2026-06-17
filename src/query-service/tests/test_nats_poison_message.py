"""Regression: poison-message phải term()+DLQ, KHÔNG nak() vô hạn (NAK-storm 2026-06-16).

Lỗi VĨNH VIỄN (bảng thiếu = sqlstate 42P01) -> term + đẩy DLQ; lỗi TẠM THỜI -> nak retry.
"""
import pytest

from app.infrastructure.messaging.nats_events import InvalidNatsEventPayload
from app.infrastructure.messaging.nats_subscriber import (
    NatsSubscriberManager,
    _is_permanent_error,
)


class _PgError(Exception):
    """Giả asyncpg.PostgresError: có .sqlstate."""
    def __init__(self, sqlstate):
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


class _FakeMsg:
    def __init__(self):
        self.subject = "hr.employee_profile.updated"
        self.data = b'{"x":1}'
        self.calls = []
    async def ack(self):
        self.calls.append("ack")
    async def nak(self):
        self.calls.append("nak")
    async def term(self):
        self.calls.append("term")


class _FakeConn:
    def __init__(self):
        self.published = []
    async def publish(self, subject, data):
        self.published.append((subject, data))


def test_is_permanent_error_classification():
    assert _is_permanent_error(_PgError("42P01")) is True   # undefined_table (sự cố thật)
    assert _is_permanent_error(_PgError("42703")) is True   # undefined_column
    assert _is_permanent_error(_PgError("23505")) is True   # unique_violation = data sai
    assert _is_permanent_error(InvalidNatsEventPayload("bad")) is True
    assert _is_permanent_error(_PgError("08006")) is False  # connection_failure = tạm thời
    assert _is_permanent_error(_PgError("40001")) is False  # serialization = tạm thời
    assert _is_permanent_error(RuntimeError("???")) is False


def _manager():
    m = NatsSubscriberManager.__new__(NatsSubscriberManager)
    import logging
    m._logger = logging.getLogger("test")
    m._connection = _FakeConn()
    return m


@pytest.mark.asyncio
async def test_permanent_error_terms_and_dlq():
    m = _manager()
    msg = _FakeMsg()

    async def handle(_payload):
        raise _PgError("42P01")  # relation does not exist

    await m._handle_message(msg, validate=lambda p: None, handle=handle)
    assert msg.calls == ["term"]                       # term, KHÔNG nak
    assert m._connection.published == [("hr.employee_profile.updated.dlq", msg.data)]


@pytest.mark.asyncio
async def test_transient_error_naks():
    m = _manager()
    msg = _FakeMsg()

    async def handle(_payload):
        raise _PgError("08006")  # connection_failure

    await m._handle_message(msg, validate=lambda p: None, handle=handle)
    assert msg.calls == ["nak"]                         # nak để retry
    assert m._connection.published == []                # không đẩy DLQ


@pytest.mark.asyncio
async def test_success_acks():
    m = _manager()
    msg = _FakeMsg()

    async def handle(_payload):
        return None

    await m._handle_message(msg, validate=lambda p: None, handle=handle)
    assert msg.calls == ["ack"]
