"""Resilience: NATS lỗi KHÔNG được làm mất đơn và KHÔNG được nuốt log.

Yêu cầu production: ghi DB là source of truth; publish event là phụ (best-effort).
Khi publish raise -> write VẪN thành công (đơn không mất) + log warning rõ ràng
(không nuốt im lặng) để vận hành biết event chưa gửi.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi.testclient import TestClient

from app.api.routes import get_publisher, get_settings, get_write_repo
from app.infrastructure import nats_publisher as np
from app.main import app
from tests.test_leave_write_endpoint import (
    EMP,
    MANAGER,
    FailingPublisher,
    FakeLeaveWriteRepo,
    _settings,
)


def test_publish_failure_keeps_order_and_logs_warning(caplog):
    repo = FakeLeaveWriteRepo()
    repo.managers[EMP] = MANAGER
    settings = _settings()
    app.dependency_overrides[get_write_repo] = lambda: repo
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_publisher] = lambda: FailingPublisher()
    client = TestClient(app)
    try:
        with caplog.at_level(logging.WARNING, logger="hr-service"):
            r = client.post("/hr/leave-requests", json={
                "user_id": EMP, "leave_type": "annual",
                "start_date": "2026-07-01", "end_date": "2026-07-02",
            })
        # Đơn KHÔNG mất: write thành công 201 dù NATS chết
        assert r.status_code == 201, r.text
        assert len(repo.requests) == 1
        rid = r.json()["id"]
        assert repo.requests[rid]["status"] == "pending"
        # KHÔNG nuốt log: có warning chỉ rõ publish fail + subject
        msgs = " ".join(rec.getMessage() for rec in caplog.records)
        assert "hr_event_publish_failed" in msgs
        assert "hr.leave_request.created" in msgs
    finally:
        app.dependency_overrides.clear()


def test_publisher_none_skips_publish_no_crash():
    """app.state.publisher chưa set (vd lifespan chưa chạy) -> get_publisher None ->
    publish bị bỏ qua, write vẫn 201 (không AttributeError)."""
    repo = FakeLeaveWriteRepo()
    repo.managers[EMP] = MANAGER
    app.dependency_overrides[get_write_repo] = lambda: repo
    app.dependency_overrides[get_settings] = lambda: _settings()
    app.dependency_overrides[get_publisher] = lambda: None
    client = TestClient(app)
    try:
        r = client.post("/hr/leave-requests", json={
            "user_id": EMP, "leave_type": "sick",
            "start_date": "2026-07-01", "end_date": "2026-07-01",
        })
        assert r.status_code == 201
    finally:
        app.dependency_overrides.clear()


# ─────────────── JetStream: bổ sung subject cho stream đã tồn tại ───────────────
class _FakeConfig:
    def __init__(self, subjects):
        self.subjects = list(subjects)


class _FakeInfo:
    def __init__(self, subjects):
        self.config = _FakeConfig(subjects)


class _FakeJs:
    """Mô phỏng stream HR_EVENTS cũ chỉ có hr.employee_profile.updated."""

    def __init__(self):
        self.updated_to = None
        self.added = None

    async def stream_info(self, name):
        return _FakeInfo(["hr.employee_profile.updated"])

    async def update_stream(self, config):
        self.updated_to = set(config.subjects)

    async def add_stream(self, name=None, subjects=None):
        self.added = (name, subjects)


def test_ensure_jetstream_adds_missing_leave_subjects():
    js = _FakeJs()
    asyncio.run(np.ensure_jetstream_streams(js))
    # Stream đã tồn tại -> KHÔNG add_stream, mà UPDATE thêm 5 subject leave_request.*
    assert js.added is None
    assert js.updated_to is not None
    for subject in np.LEAVE_REQUEST_SUBJECTS:
        assert subject in js.updated_to
    assert "hr.employee_profile.updated" in js.updated_to


class _FakeJsNoStream:
    def __init__(self):
        self.added = None

    async def stream_info(self, name):
        raise RuntimeError("not found")

    async def add_stream(self, name=None, subjects=None):
        self.added = (name, list(subjects))


def test_ensure_jetstream_creates_stream_with_all_subjects():
    js = _FakeJsNoStream()
    asyncio.run(np.ensure_jetstream_streams(js))
    assert js.added is not None
    name, subjects = js.added
    assert name == "HR_EVENTS"
    for subject in np.LEAVE_REQUEST_SUBJECTS:
        assert subject in subjects
