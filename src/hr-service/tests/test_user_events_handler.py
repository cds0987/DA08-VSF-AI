"""Test handler user.* (đồng bộ danh tính) — fail-fast, không NATS thật, không sleep.

handle_user_event tách khỏi NATS nên test gọi trực tiếp với fake repo: nhanh, lỗi nổ
ngay, không nuốt log.
"""
from __future__ import annotations

import asyncio

import pytest

from app.infrastructure.user_events_subscriber import handle_user_event


class RecordingRepo:
    def __init__(self) -> None:
        self.ensured: list[str] = []
        self.upserts: list[tuple[str, str, str, bool]] = []

    async def ensure_leave_balance(self, user_id: str) -> None:
        self.ensured.append(user_id)

    async def upsert_employee_from_user(
        self, user_id: str, email: str, department: str, is_active: bool
    ) -> None:
        self.upserts.append((user_id, email, department, is_active))

    async def aclose(self) -> None:  # pragma: no cover - không dùng ở handler test
        return None


def _run(coro):
    return asyncio.run(coro)


def test_user_created_provisions_employee_and_leave_balance() -> None:
    repo = RecordingRepo()
    payload = {
        "user_id": "u-1",
        "email": "a@b.c",
        "department": "HR",
        "is_active": True,
    }
    _run(handle_user_event("user.created", payload, repo))
    assert repo.upserts == [("u-1", "a@b.c", "HR", True)]
    assert repo.ensured == ["u-1"]


def test_user_deactivated_sets_inactive_no_leave_balance() -> None:
    repo = RecordingRepo()
    payload = {"user_id": "u-2", "email": "x@y.z", "department": "Fin", "is_active": False}
    _run(handle_user_event("user.deactivated", payload, repo))
    assert repo.upserts == [("u-2", "x@y.z", "Fin", False)]
    assert repo.ensured == []  # không tạo phép cho user nghỉ việc


def test_user_deactivated_defaults_inactive_when_flag_missing() -> None:
    repo = RecordingRepo()
    # is_active vắng -> suy ra từ subject deactivated.
    _run(handle_user_event("user.deactivated", {"user_id": "u-3"}, repo))
    assert repo.upserts == [("u-3", "", "", False)]


def test_missing_user_id_raises_fast() -> None:
    repo = RecordingRepo()
    with pytest.raises((KeyError, ValueError)):
        _run(handle_user_event("user.created", {"email": "a@b.c"}, repo))
    assert repo.upserts == []
