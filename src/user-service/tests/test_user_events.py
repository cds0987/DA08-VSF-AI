"""Test phát event vòng đời user — fail-fast, không NATS thật, không sleep.

- SetUserActiveUseCase phải emit đúng subject (updated/deactivated) qua emitter.
- NatsUserEventEmitter best-effort: lỗi publish KHÔNG raise (không làm hỏng nghiệp vụ).
- build_user_event: payload đủ field theo subjects.md.
"""
from __future__ import annotations

import asyncio

from app.application.use_cases.users.set_user_active_use_case import SetUserActiveUseCase
from app.domain.entities.user import User, UserRole
from app.infrastructure.messaging.user_event_emitter import NatsUserEventEmitter
from app.infrastructure.messaging.user_event_publisher import build_user_event


def _run(coro):
    return asyncio.run(coro)


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
