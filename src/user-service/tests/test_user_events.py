"""Test phát event vòng đời user — fail-fast, không NATS thật, không sleep.

- SetUserActiveUseCase phải emit đúng subject (updated/deactivated) qua emitter.
- NatsUserEventEmitter best-effort: lỗi publish KHÔNG raise (không làm hỏng nghiệp vụ).
- build_user_event: payload đủ field theo subjects.md.
"""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from app.application.use_cases.users.set_user_active_use_case import SetUserActiveUseCase
from app.domain.entities.user import User, UserRole
from app.infrastructure.messaging.user_event_emitter import NatsUserEventEmitter
from app.infrastructure.messaging.user_event_publisher import build_user_event


def _run(coro):
    return asyncio.run(coro)


def _load_backfill_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "backfill_user_events.py"
    spec = importlib.util.spec_from_file_location("user_backfill_user_events", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeUserRepo:
    def __init__(self, user: User) -> None:
        self._user = user

    async def set_active(self, user_id: str, is_active: bool):
        return User(
            id=self._user.id,
            email=self._user.email,
            role=self._user.role,
            is_active=is_active,
            account_type=self._user.account_type,
            department=self._user.department,
        )


class FakeAudit:
    async def log(self, **kwargs) -> None:
        return None


class RecordingEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def emit(self, subject: str, user: User) -> None:
        self.events.append((subject, user.id))


ADMIN = User(id="admin-1", email="admin@c.com", role=UserRole.ADMIN, department="HR")
TARGET = User(id="u-9", email="u9@c.com", role=UserRole.USER, department="Fin")


def test_deactivate_emits_user_deactivated() -> None:
    emitter = RecordingEmitter()
    uc = SetUserActiveUseCase(FakeUserRepo(TARGET), FakeAudit(), event_emitter=emitter)
    _run(uc.execute(actor=ADMIN, user_id="u-9", is_active=False))
    assert emitter.events == [("user.deactivated", "u-9")]


def test_reactivate_emits_user_updated() -> None:
    emitter = RecordingEmitter()
    uc = SetUserActiveUseCase(FakeUserRepo(TARGET), FakeAudit(), event_emitter=emitter)
    _run(uc.execute(actor=ADMIN, user_id="u-9", is_active=True))
    assert emitter.events == [("user.updated", "u-9")]


def test_no_emitter_does_not_fail() -> None:
    uc = SetUserActiveUseCase(FakeUserRepo(TARGET), FakeAudit(), event_emitter=None)
    result = _run(uc.execute(actor=ADMIN, user_id="u-9", is_active=False))
    assert result.is_active is False


class ExplodingPublisher:
    async def publish_user_event(self, subject: str, user: dict) -> None:
        raise RuntimeError("nats down")


def test_emitter_is_best_effort_swallows_publish_error() -> None:
    emitter = NatsUserEventEmitter(ExplodingPublisher())
    # KHÔNG được raise (best-effort) — lỗi đã log warning bên trong.
    _run(emitter.emit("user.updated", TARGET))


def test_build_user_event_has_required_fields() -> None:
    payload = build_user_event(
        {"user_id": "u-9", "email": "u9@c.com", "role": "user", "department": "Fin"}
    )
    for key in (
        "event_id",
        "event_version",
        "occurred_at",
        "user_id",
        "email",
        "role",
        "department",
        "account_type",
        "is_active",
    ):
        assert key in payload
    assert payload["occurred_at"].endswith("Z")


class RecordingBackfillPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def publish_user_event(self, subject: str, user: dict) -> None:
        self.calls.append((subject, user))


class ExplodingBackfillPublisher:
    def __init__(self) -> None:
        self.calls = 0

    async def publish_user_event(self, subject: str, user: dict) -> None:
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("publish failed")


def test_backfill_publishes_user_created_for_every_user() -> None:
    module = _load_backfill_module()
    publisher = RecordingBackfillPublisher()
    users = [
        SimpleNamespace(
            id="u-1",
            email="u1@company.com",
            role=UserRole.ADMIN,
            department="HR",
            account_type="internal",
            is_active=True,
        ),
        SimpleNamespace(
            id="u-2",
            email="u2@company.com",
            role=UserRole.USER,
            department="Fin",
            account_type="external",
            is_active=False,
        ),
        SimpleNamespace(
            id="u-3",
            email="u3@company.com",
            role=UserRole.USER,
            department="IT",
            account_type="internal",
            is_active=True,
        ),
    ]

    sent = _run(module.backfill_users(users, publisher))

    assert sent == 3
    assert [subject for subject, _ in publisher.calls] == ["user.created", "user.created", "user.created"]
    for _, payload in publisher.calls:
        for key in ("user_id", "email", "role", "department", "account_type", "is_active"):
            assert key in payload


def test_backfill_fails_fast_when_publish_raises() -> None:
    module = _load_backfill_module()
    publisher = ExplodingBackfillPublisher()
    users = [
        SimpleNamespace(
            id="u-1",
            email="u1@company.com",
            role=UserRole.ADMIN,
            department="HR",
            account_type="internal",
            is_active=True,
        ),
        SimpleNamespace(
            id="u-2",
            email="u2@company.com",
            role=UserRole.USER,
            department="Fin",
            account_type="internal",
            is_active=True,
        ),
    ]

    try:
        _run(module.backfill_users(users, publisher))
    except RuntimeError as exc:
        assert "publish failed" in str(exc)
    else:  # pragma: no cover - fail-fast contract
        raise AssertionError("backfill_users should fail fast when publish raises")
