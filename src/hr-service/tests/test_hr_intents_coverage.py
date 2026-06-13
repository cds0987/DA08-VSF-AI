"""Bổ sung coverage hr-service (T5).

Phủ các intent READ chưa có test endpoint (leave_requests / attendance / onboarding)
ở cả happy + NO_INFO, audit path cho 3 intent nhạy cảm (payroll/benefits/performance),
self-access (user A ≠ user B), và giữ dấu Unicode tiếng Việt trong summary.
Tái dùng FakeHrRepository từ test_hr_query_endpoint để bám đúng hành vi hiện có.
"""
from __future__ import annotations

import logging

from fastapi.testclient import TestClient

import app.core.config as core_config
from app.api.routes import get_repo, get_settings
from app.core.config import HrSettings
from app.main import app

from tests.test_hr_query_endpoint import (
    FakeHrRepository,
    USER_FINANCE,
    USER_HR,
)

TOKEN = "dev-secret"
UNKNOWN_USER = "99999999-9999-4999-8999-999999999999"

_SETTINGS = dict(
    host="0.0.0.0",
    port=8004,
    log_level="INFO",
    database_url="",
    internal_token=TOKEN,
    auto_provision_leave_balance=True,
    default_annual_leave=12,
    default_sick_leave=10,
    nats_url="nats://localhost:4222",
    nats_jetstream_enabled=False,
    user_events_enabled=False,
)


def setup_module() -> None:
    app.dependency_overrides.clear()
    app.dependency_overrides[get_repo] = lambda: FakeHrRepository()
    app.dependency_overrides[get_settings] = lambda: HrSettings(**_SETTINGS)
    app.dependency_overrides[core_config.get_settings] = lambda: HrSettings(**_SETTINGS)


def teardown_module() -> None:
    app.dependency_overrides.clear()


def _post(intent: str, user_id: str = USER_HR):
    client = TestClient(app)
    return client.post(
        "/hr/query",
        json={"user_id": user_id, "intent": intent},
        headers={"X-Internal-Token": TOKEN},
    )


# ─────────────────────── leave_requests ───────────────────────

def test_leave_requests_happy():
    resp = _post("leave_requests")
    assert resp.status_code == 200
    body = resp.json()
    assert body["intent"] == "leave_requests"
    assert len(body["data"]["requests"]) == 2
    assert "Đơn nghỉ gần nhất" in body["summary"]


def test_leave_requests_empty_user_returns_friendly_summary():
    # User lạ: FakeHrRepository.get_leave_requests trả [] -> summary "chưa có đơn", 200.
    resp = _post("leave_requests", user_id=UNKNOWN_USER)
    assert resp.status_code == 200
    assert resp.json()["summary"] == "Bạn chưa có đơn nghỉ phép nào."


# ─────────────────────── attendance ───────────────────────

def test_attendance_happy():
    resp = _post("attendance")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["work_days"] == 20
    assert "ngày công" in resp.json()["summary"]


def test_attendance_unknown_user_404():
    resp = _post("attendance", user_id=UNKNOWN_USER)
    assert resp.status_code == 404


# ─────────────────────── onboarding ───────────────────────

def test_onboarding_happy():
    resp = _post("onboarding")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["completed_count"] == 3
    assert data["total_count"] == 3


def test_onboarding_unknown_user_404():
    resp = _post("onboarding", user_id=UNKNOWN_USER)
    assert resp.status_code == 404


# ─────────────────────── audit path (3 intent nhạy cảm) ───────────────────────

def test_payroll_writes_audit_log(caplog):
    with caplog.at_level(logging.INFO, logger="hr-service"):
        resp = _post("payroll")
    assert resp.status_code == 200
    assert any("hr_audit" in r.getMessage() and "payroll" in r.getMessage() for r in caplog.records)


def test_benefits_writes_audit_log(caplog):
    with caplog.at_level(logging.INFO, logger="hr-service"):
        resp = _post("benefits")
    assert resp.status_code == 200
    assert any("hr_audit" in r.getMessage() and "benefits" in r.getMessage() for r in caplog.records)


def test_performance_writes_audit_log(caplog):
    with caplog.at_level(logging.INFO, logger="hr-service"):
        resp = _post("performance")
    assert resp.status_code == 200
    assert any("hr_audit" in r.getMessage() and "performance" in r.getMessage() for r in caplog.records)


def test_non_sensitive_intent_no_audit_log(caplog):
    # leave_balance KHÔNG nhạy cảm -> không ghi audit.
    with caplog.at_level(logging.INFO, logger="hr-service"):
        resp = _post("leave_balance")
    assert resp.status_code == 200
    assert not any("hr_audit" in r.getMessage() for r in caplog.records)


def test_audit_log_masks_user_id(caplog):
    # Audit KHÔNG được lộ user_id gốc (mask sha256 12 ký tự).
    with caplog.at_level(logging.INFO, logger="hr-service"):
        _post("payroll")
    audit_msgs = [r.getMessage() for r in caplog.records if "hr_audit" in r.getMessage()]
    assert audit_msgs
    assert all(USER_HR not in msg for msg in audit_msgs)


# ─────────────────────── self-access / isolation ───────────────────────

def test_self_access_isolation_payroll():
    # Cùng intent, 2 user khác nhau -> dữ liệu khác nhau (lọc theo user_id).
    a = _post("payroll", user_id=USER_HR).json()["data"]
    b = _post("payroll", user_id=USER_FINANCE).json()["data"]
    assert a != b


# ─────────────────────── Unicode tiếng Việt ───────────────────────

def test_summary_preserves_vietnamese_diacritics():
    resp = _post("leave_balance")
    summary = resp.json()["summary"]
    # Dấu tiếng Việt phải giữ nguyên, không bị mất dấu / mojibake.
    assert "ngày phép" in summary
    assert "Bạn còn" in summary
