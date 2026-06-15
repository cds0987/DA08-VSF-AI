"""Test handler user.* (đồng bộ danh tính) — fail-fast, không NATS thật, không sleep.

handle_user_event tách khỏi NATS nên test gọi trực tiếp với fake repo: nhanh, lỗi nổ
ngay, không nuốt log.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from app.infrastructure.user_events_subscriber import (
    USER_EVENT_SUBJECTS,
    handle_user_event,
    start_user_events_subscriber,
)


class RecordingRepo:
    def __init__(self) -> None:
        self.ensured: list[str] = []
        self.upserts: list[tuple[str, str, str, bool, str]] = []

    async def ensure_leave_balance(
        self, user_id: str, annual_total: int = 12, sick_total: int = 10
    ) -> None:
        self.ensured.append(user_id)
        self.ensured_totals = (annual_total, sick_total)

    async def upsert_employee_from_user(
        self, user_id: str, email: str, department: str, is_active: bool, account_type: str
    ) -> None:
        self.upserts.append((user_id, email, department, is_active, account_type))


    async def aclose(self) -> None:  # pragma: no cover - không dùng ở handler test
        return None


class ExplodingRepo(RecordingRepo):
    async def upsert_employee_from_user(
        self, user_id: str, email: str, department: str, is_active: bool, account_type: str
    ) -> None:
        raise RuntimeError("db write failed")


class RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[dict[str, str]] = []

    async def publish_profile_updated(self, payload: dict[str, str]) -> None:
        self.events.append(payload)


class ExplodingPublisher:
    async def publish_profile_updated(self, payload: dict[str, str]) -> None:
        raise RuntimeError("nats publish failed")


def _run(coro):
    return asyncio.run(coro)


def test_user_created_provisions_employee_and_leave_balance() -> None:
    repo = RecordingRepo()
    publisher = RecordingPublisher()
    payload = {
        "user_id": "u-1",
        "email": "a@b.c",
        "department": "HR",
        "account_type": "internal",
        "is_active": True,
    }
    _run(handle_user_event("user.created", payload, repo, publisher))
    assert repo.upserts == [("u-1", "a@b.c", "HR", True, "internal")]
    assert repo.ensured == ["u-1"]
    assert publisher.events == [
        {
            "user_id": "u-1",
            "account_type": "internal",
            "department": "HR",
            "employment_status": "active",
        }
    ]


def test_user_created_uses_config_default_leave_limits() -> None:
    repo = RecordingRepo()
    payload = {"user_id": "u-9", "email": "a@b.c", "department": "HR", "is_active": True}
    _run(
        handle_user_event(
            "user.created", payload, repo, default_annual_leave=18, default_sick_leave=5
        )
    )
    assert repo.ensured == ["u-9"]
    assert repo.ensured_totals == (18, 5)


def test_user_deactivated_sets_inactive_no_leave_balance() -> None:
    repo = RecordingRepo()
    publisher = RecordingPublisher()
    payload = {"user_id": "u-2", "email": "x@y.z", "department": "Fin", "is_active": False}
    _run(handle_user_event("user.deactivated", payload, repo, publisher))
    assert repo.upserts == [("u-2", "x@y.z", "Fin", False, "internal")]
    assert repo.ensured == []  # không tạo phép cho user nghỉ việc
    assert publisher.events == [
        {
            "user_id": "u-2",
            "account_type": "internal",
            "department": "Fin",
            "employment_status": "inactive",
        }
    ]


def test_user_deactivated_defaults_inactive_when_flag_missing() -> None:
    repo = RecordingRepo()
    # is_active vắng -> suy ra từ subject deactivated.
    _run(handle_user_event("user.deactivated", {"user_id": "u-3"}, repo))
    assert repo.upserts == [("u-3", "", "", False, "internal")]


def test_missing_user_id_raises_fast() -> None:
    repo = RecordingRepo()
    with pytest.raises((KeyError, ValueError)):
        _run(handle_user_event("user.created", {"email": "a@b.c"}, repo))
    assert repo.upserts == []


def test_publish_error_is_best_effort_and_does_not_break_db_sync() -> None:
    repo = RecordingRepo()
    payload = {
        "user_id": "u-4",
        "email": "u4@company.com",
        "department": "Ops",
        "account_type": "external",
        "is_active": True,
    }

    _run(handle_user_event("user.updated", payload, repo, ExplodingPublisher()))

    assert repo.upserts == [("u-4", "u4@company.com", "Ops", True, "external")]
    assert repo.ensured == ["u-4"]


def test_db_error_still_raises_for_retry() -> None:
    repo = ExplodingRepo()
    payload = {"user_id": "u-5", "email": "u5@company.com", "department": "IT", "is_active": True}

    with pytest.raises(RuntimeError, match="db write failed"):
        _run(handle_user_event("user.created", payload, repo, RecordingPublisher()))


@dataclass(frozen=True)
class FakeSettings:
    nats_url: str = "nats://nats:4222"
    nats_jetstream_enabled: bool = True
    user_events_enabled: bool = True
    default_annual_leave: int = 12
    default_sick_leave: int = 10


class FakeConnection:
    def __init__(self, jetstream) -> None:
        self._jetstream = jetstream
        self.drained = False

    def jetstream(self):
        return self._jetstream

    async def drain(self) -> None:
        self.drained = True


class FakeJetStream:
    def __init__(self) -> None:
        self.subscriptions: list[tuple[str, str]] = []

    async def subscribe(self, subject: str, durable: str, cb) -> None:
        self.subscriptions.append((subject, durable))


class FakeNatsModule:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    async def connect(self, url: str):
        return self.connection


def test_duplicate_user_created_is_idempotent() -> None:
    """Gọi handle_user_event hai lần cho cùng user_id không raise và cả hai lần
    đều gọi upsert (DB xử lý ON CONFLICT). Không có exception propagate."""
    repo = RecordingRepo()
    publisher = RecordingPublisher()
    payload = {
        "user_id": "u-dup",
        "email": "dup@company.com",
        "department": "HR",
        "account_type": "internal",
        "is_active": True,
    }
    _run(handle_user_event("user.created", payload, repo, publisher))
    _run(handle_user_event("user.created", payload, repo, publisher))

    # Cả hai lần đều gọi upsert — ON CONFLICT ở postgres layer mới dedup
    assert len(repo.upserts) == 2
    for upsert in repo.upserts:
        assert upsert[0] == "u-dup"


def test_subscriber_only_registers_user_subjects() -> None:
    jetstream = FakeJetStream()
    connection = FakeConnection(jetstream)
    settings = FakeSettings()

    handle = _run(
        start_user_events_subscriber(
            settings,  # type: ignore[arg-type]
            repo_factory=RecordingRepo,
            publisher=RecordingPublisher(),
            nats_module=FakeNatsModule(connection),
        )
    )

    try:
        assert [subject for subject, _ in jetstream.subscriptions] == list(USER_EVENT_SUBJECTS)
        assert all(not subject.startswith("hr.") for subject, _ in jetstream.subscriptions)
    finally:
        _run(handle.close())
