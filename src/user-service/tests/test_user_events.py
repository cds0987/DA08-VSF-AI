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
from app.infrastructure.messaging.user_event_publisher import _ensure_streams, build_user_event


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
        )


class FakeAudit:
    async def log(self, **kwargs) -> None:
        return None


class RecordingEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def emit(self, subject: str, user: User) -> None:
        self.events.append((subject, user.id))


ADMIN = User(id="admin-1", email="admin@c.com", role=UserRole.ADMIN)
TARGET = User(id="u-9", email="u9@c.com", role=UserRole.USER)


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
        {"user_id": "u-9", "email": "u9@c.com", "role": "user"}
    )
    for key in (
        "event_id",
        "event_version",
        "occurred_at",
        "user_id",
        "email",
        "role",
        "account_type",
        "is_active",
    ):
        assert key in payload
    assert "department" not in payload
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
            account_type="internal",
            is_active=True,
        ),
        SimpleNamespace(
            id="u-2",
            email="u2@company.com",
            role=UserRole.USER,
            account_type="external",
            is_active=False,
        ),
        SimpleNamespace(
            id="u-3",
            email="u3@company.com",
            role=UserRole.USER,
            account_type="internal",
            is_active=True,
        ),
    ]

    sent = _run(module.backfill_users(users, publisher))

    assert sent == 3
    assert [subject for subject, _ in publisher.calls] == ["user.created", "user.created", "user.created"]
    for _, payload in publisher.calls:
        for key in ("user_id", "email", "role", "account_type", "is_active"):
            assert key in payload
        assert "department" not in payload


def test_backfill_fails_fast_when_publish_raises() -> None:
    module = _load_backfill_module()
    publisher = ExplodingBackfillPublisher()
    users = [
        SimpleNamespace(
            id="u-1",
            email="u1@company.com",
            role=UserRole.ADMIN,
            account_type="internal",
            is_active=True,
        ),
        SimpleNamespace(
            id="u-2",
            email="u2@company.com",
            role=UserRole.USER,
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


# ─────────── _ensure_streams: reconcile USER_EVENTS subjects ───────────

class _FakeStreamConfig:
    def __init__(self, subjects):
        self.subjects = list(subjects)


class _FakeStreamInfo:
    def __init__(self, subjects):
        self.config = _FakeStreamConfig(subjects)


class _FakeJsExisting:
    """Giả lập stream USER_EVENTS đã tồn tại với 3 subject cũ (chưa có user.deleted)."""

    def __init__(self):
        self.updated_to = None
        self.added = None

    async def stream_info(self, name):
        return _FakeStreamInfo(["user.created", "user.updated", "user.deactivated"])

    async def update_stream(self, config):
        self.updated_to = set(config.subjects)

    async def add_stream(self, name=None, subjects=None):  # pragma: no cover
        self.added = (name, subjects)


class _FakeJsNoStream:
    """Giả lập chưa có stream."""

    def __init__(self):
        self.added = None

    async def stream_info(self, name):
        raise RuntimeError("stream not found")

    async def add_stream(self, name=None, subjects=None):
        self.added = (name, list(subjects))

    async def update_stream(self, config):  # pragma: no cover
        pass


def test_ensure_streams_updates_existing_stream_with_missing_subject() -> None:
    """Stream đã tồn tại thiếu user.deleted -> update_stream bổ sung, không add_stream."""
    js = _FakeJsExisting()
    _run(_ensure_streams(js))
    assert js.added is None, "không được tạo stream mới khi đã tồn tại"
    assert js.updated_to is not None, "phải gọi update_stream"
    assert "user.deleted" in js.updated_to
    assert "user.created" in js.updated_to
    assert "user.updated" in js.updated_to
    assert "user.deactivated" in js.updated_to


def test_ensure_streams_creates_stream_when_not_found() -> None:
    """Stream chưa tồn tại -> add_stream với đủ 4 subject, không update_stream."""
    js = _FakeJsNoStream()
    _run(_ensure_streams(js))
    assert js.added is not None, "phải gọi add_stream"
    name, subjects = js.added
    assert name == "USER_EVENTS"
    for subject in ("user.created", "user.updated", "user.deactivated", "user.deleted"):
        assert subject in subjects


def test_ensure_streams_noop_when_subjects_already_complete() -> None:
    """Stream đã đủ 4 subject -> không gọi update_stream."""

    class _FakeJsFull(_FakeJsExisting):
        async def stream_info(self, name):
            return _FakeStreamInfo(
                ["user.created", "user.updated", "user.deactivated", "user.deleted"]
            )

    js = _FakeJsFull()
    _run(_ensure_streams(js))
    assert js.updated_to is None, "đã đủ subject thì không được update"
    assert js.added is None
