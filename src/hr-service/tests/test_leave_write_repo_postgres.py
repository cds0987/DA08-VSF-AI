"""Production-fidelity: chạy LeaveWrite trên PostgresHrRepository THẬT + Postgres THẬT.

Phủ đúng code production mà fake không chạm tới: transaction, SELECT ... FOR UPDATE,
phép toán balance trong DB, ràng buộc UNIQUE idempotency_key, rollback khi thiếu phép.

Guard bằng env HR_TEST_DATABASE_URL -> CI Phase 1 (infra off) tự SKIP, không làm đỏ
pipeline. Chạy cục bộ / trong stack e2e:

    HR_TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/hr \
        python -m pytest tests/test_leave_write_repo_postgres.py -q

(dùng schema riêng hr_svc, tạo/drop trong fixture -> không đụng data khác.)
"""
from __future__ import annotations

import asyncio
import datetime
import os
import uuid

import pytest
import sqlalchemy as sa

from app.domain.repositories.leave_write_repository import (
    InsufficientLeaveBalance,
    LeaveRequestConflict,
    LeaveRequestDuplicate,
    LeaveRequestForbidden,
    LeaveRequestOverlapWarning,
)

DB_URL = os.environ.get("HR_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DB_URL, reason="HR_TEST_DATABASE_URL chưa set -> bỏ qua test real-Postgres"
)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def repo():
    from app.infrastructure.db.models import Base
    from app.infrastructure.db.postgres_hr_repository import PostgresHrRepository

    engine = sa.create_engine(DB_URL)
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE SCHEMA IF NOT EXISTS hr_svc"))
    Base.metadata.create_all(engine)

    r = PostgresHrRepository(DB_URL)
    try:
        yield r, engine
    finally:
        _run(r.aclose())
        Base.metadata.drop_all(engine)
        with engine.begin() as conn:
            conn.execute(sa.text("DROP SCHEMA IF EXISTS hr_svc CASCADE"))
        engine.dispose()


def _seed_employee(engine, user_id, manager_user_id):
    now = datetime.datetime.now(datetime.timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO hr_svc.employees "
                "(id, user_id, company_email, department, manager_user_id, "
                " employment_status, created_at, updated_at) "
                "VALUES (:id, :uid, :email, 'eng', :mgr, 'active', :now, :now)"
            ),
            {"id": str(uuid.uuid4()), "uid": user_id, "email": f"{user_id[:8]}@x.local",
             "mgr": manager_user_id, "now": now},
        )


def _seed_balance(engine, user_id, annual_total=12, annual_used=0, sick_total=10, sick_used=0):
    now = datetime.datetime.now(datetime.timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO hr_svc.leave_balance "
                "(user_id, annual_leave_total, annual_leave_used, sick_leave_total, "
                " sick_leave_used, updated_at) "
                "VALUES (:uid, :at, :au, :st, :su, :now)"
            ),
            {"uid": user_id, "at": annual_total, "au": annual_used, "st": sick_total,
             "su": sick_used, "now": now},
        )


def _balance(engine, user_id):
    with engine.begin() as conn:
        row = conn.execute(
            sa.text("SELECT annual_leave_used, sick_leave_used FROM hr_svc.leave_balance "
                    "WHERE user_id = :uid"),
            {"uid": user_id},
        ).first()
    return (row[0], row[1]) if row else None


EMP = "11111111-1111-4111-8111-111111111111"
MANAGER = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"


def test_create_resolves_manager(repo):
    r, engine = repo
    _seed_employee(engine, EMP, MANAGER)
    out = _run(r.create_leave_request(
        user_id=EMP, leave_type="annual", start_date="2026-07-01",
        end_date="2026-07-03", reason="x", default_approver="", idempotency_key="k1"))
    assert out["created"] is True
    assert out["request"]["approver_user_id"] == MANAGER
    assert out["request"]["days_count"] == 3
    assert out["request"]["status"] == "pending"


def test_idempotency_unique_no_duplicate(repo):
    r, engine = repo
    _seed_employee(engine, EMP, MANAGER)
    a = _run(r.create_leave_request(user_id=EMP, leave_type="annual", start_date="2026-07-01",
             end_date="2026-07-02", reason="", default_approver="", idempotency_key="dup"))
    b = _run(r.create_leave_request(user_id=EMP, leave_type="annual", start_date="2026-07-01",
             end_date="2026-07-02", reason="", default_approver="", idempotency_key="dup"))
    assert a["request"]["id"] == b["request"]["id"]
    assert b["created"] is False
    with engine.begin() as conn:
        count = conn.execute(sa.text("SELECT count(*) FROM hr_svc.leave_requests")).scalar()
    assert count == 1


def test_create_exact_duplicate_rejected(repo):
    """Key khác nhau nhưng TRÙNG TOÀN BỘ (loại+ngày+lý do) -> LeaveRequestDuplicate."""
    r, engine = repo
    _seed_employee(engine, EMP, MANAGER)
    first = _run(r.create_leave_request(
        user_id=EMP, leave_type="personal", start_date="2026-07-10",
        end_date="2026-07-10", reason="cá nhân", default_approver="", idempotency_key="a"))
    assert first["created"] is True
    with pytest.raises(LeaveRequestDuplicate):
        _run(r.create_leave_request(
            user_id=EMP, leave_type="personal", start_date="2026-07-10",
            end_date="2026-07-10", reason="cá nhân", default_approver="", idempotency_key="b"))
    with engine.begin() as conn:
        count = conn.execute(sa.text("SELECT count(*) FROM hr_svc.leave_requests")).scalar()
    assert count == 1


def test_create_overlap_warns_then_confirm_creates(repo):
    """Cùng/đè ngày nhưng KHÁC nội dung -> cảnh báo OverlapWarning (kèm đơn cũ);
    gọi lại confirm_overlap=True -> tạo được."""
    r, engine = repo
    _seed_employee(engine, EMP, MANAGER)
    _run(r.create_leave_request(
        user_id=EMP, leave_type="personal", start_date="2026-07-11",
        end_date="2026-07-11", reason="khám bệnh", default_approver="", idempotency_key="c"))
    with pytest.raises(LeaveRequestOverlapWarning) as ei:
        _run(r.create_leave_request(
            user_id=EMP, leave_type="personal", start_date="2026-07-11",
            end_date="2026-07-11", reason="việc gia đình", default_approver="", idempotency_key="d"))
    assert ei.value.existing and ei.value.existing[0]["start_date"] == "2026-07-11"
    # User xác nhận vẫn tạo -> bỏ qua cảnh báo.
    out = _run(r.create_leave_request(
        user_id=EMP, leave_type="personal", start_date="2026-07-11",
        end_date="2026-07-11", reason="việc gia đình", default_approver="",
        idempotency_key="d", confirm_overlap=True))
    assert out["created"] is True
    with engine.begin() as conn:
        count = conn.execute(sa.text("SELECT count(*) FROM hr_svc.leave_requests")).scalar()
    assert count == 2


def test_approve_deducts_then_cancel_refunds(repo):
    r, engine = repo
    _seed_employee(engine, EMP, MANAGER)
    _seed_balance(engine, EMP, annual_total=12, annual_used=0)
    rid = _run(r.create_leave_request(user_id=EMP, leave_type="annual", start_date="2026-07-01",
               end_date="2026-07-03", reason="", default_approver=""))["request"]["id"]
    _run(r.update_leave_status(request_id=rid, approver_user_id=MANAGER, action="approve"))
    assert _balance(engine, EMP) == (3, 0)
    _run(r.cancel_leave_request(user_id=EMP, request_id=rid))
    assert _balance(engine, EMP) == (0, 0)


def test_approve_insufficient_keeps_pending_and_balance(repo):
    r, engine = repo
    _seed_employee(engine, EMP, MANAGER)
    _seed_balance(engine, EMP, annual_total=12, annual_used=11)
    rid = _run(r.create_leave_request(user_id=EMP, leave_type="annual", start_date="2026-07-01",
               end_date="2026-07-03", reason="", default_approver=""))["request"]["id"]  # 3 days
    with pytest.raises(InsufficientLeaveBalance):
        _run(r.update_leave_status(request_id=rid, approver_user_id=MANAGER, action="approve"))
    # rollback: đơn giữ pending, balance KHÔNG đổi
    assert _balance(engine, EMP) == (11, 0)
    with engine.begin() as conn:
        status = conn.execute(
            sa.text("SELECT status FROM hr_svc.leave_requests WHERE id = :id"),
            {"id": rid}).scalar()
    assert status == "pending"


def test_update_approved_replaces_and_refunds(repo):
    r, engine = repo
    _seed_employee(engine, EMP, MANAGER)
    _seed_balance(engine, EMP, annual_total=12, annual_used=0)
    rid = _run(r.create_leave_request(user_id=EMP, leave_type="annual", start_date="2026-07-01",
               end_date="2026-07-02", reason="", default_approver=""))["request"]["id"]
    _run(r.update_leave_status(request_id=rid, approver_user_id=MANAGER, action="approve"))
    assert _balance(engine, EMP) == (2, 0)
    out = _run(r.update_leave_request(user_id=EMP, request_id=rid, leave_type="annual",
               start_date="2026-08-01", end_date="2026-08-01", reason="dời",
               default_approver="", idempotency_key="edit1"))
    assert out["mode"] == "replaced"
    assert out["request"]["id"] != rid
    assert out["request"]["status"] == "pending"
    assert _balance(engine, EMP) == (0, 0)  # refund đơn cũ


def test_wrong_approver_forbidden(repo):
    r, engine = repo
    _seed_employee(engine, EMP, MANAGER)
    rid = _run(r.create_leave_request(user_id=EMP, leave_type="annual", start_date="2026-07-01",
               end_date="2026-07-02", reason="", default_approver=""))["request"]["id"]
    with pytest.raises(LeaveRequestForbidden):
        _run(r.update_leave_status(request_id=rid, approver_user_id=OTHER, action="approve"))


def test_approve_already_decided_conflict(repo):
    r, engine = repo
    _seed_employee(engine, EMP, MANAGER)
    _seed_balance(engine, EMP)
    rid = _run(r.create_leave_request(user_id=EMP, leave_type="annual", start_date="2026-07-01",
               end_date="2026-07-02", reason="", default_approver=""))["request"]["id"]
    _run(r.update_leave_status(request_id=rid, approver_user_id=MANAGER, action="approve"))
    with pytest.raises(LeaveRequestConflict):
        _run(r.update_leave_status(request_id=rid, approver_user_id=MANAGER, action="approve"))
