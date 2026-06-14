"""Test endpoint LEAVE WRITE qua FastAPI app thật (TestClient) — mô phỏng đúng
contract HTTP production: routing, Pydantic validation, dependency injection, map
lỗi -> HTTP code, và publish event SAU thao tác.

Phase 1 CI chạy infra OFF (không DB) -> dùng FakeLeaveWriteRepository TRUNG THỰC
(mirror đúng state machine + balance của PostgresHrRepository). Logic transaction/
SQL thật của repo được phủ ở test real-Postgres (test_leave_write_repo_postgres.py,
guard env) + e2e. KHÔNG đụng FakeHrRepository (read) -> Bẫy 1.
"""
from __future__ import annotations

from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_publisher, get_settings, get_write_repo
from app.core.config import HrSettings
from app.domain.repositories.leave_write_repository import (
    ApproverNotConfigured,
    InsufficientLeaveBalance,
    LeaveRequestConflict,
    LeaveRequestForbidden,
    LeaveRequestNotFound,
    LeaveWriteRepository,
)
from app.main import app

EMP = "11111111-1111-4111-8111-111111111111"
MANAGER = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"
DEFAULT_APPROVER = "99999999-9999-4999-8999-999999999999"


# ───────────────────────── Fake repo trung thực ─────────────────────────
class FakeLeaveWriteRepo(LeaveWriteRepository):
    """In-memory, mirror ĐÚNG semantics của PostgresHrRepository (guard, balance,
    idempotency, mode replaced/updated). Expose store để test assert balance."""

    def __init__(self) -> None:
        self.requests: dict[str, dict] = {}
        # user_id -> {annual_total, annual_used, sick_total, sick_used}
        self.balances: dict[str, dict] = {}
        self.managers: dict[str, str] = {}
        self._seq = 0

    # helpers test
    def seed_balance(self, uid: str, annual_total=12, annual_used=0, sick_total=10, sick_used=0):
        self.balances[uid] = {
            "annual_total": annual_total, "annual_used": annual_used,
            "sick_total": sick_total, "sick_used": sick_used,
        }

    def _new_id(self) -> str:
        self._seq += 1
        return f"req-{self._seq:04d}"

    def _resolve(self, user_id: str, default_approver: str) -> str:
        approver = (self.managers.get(user_id) or "").strip() or (default_approver or "").strip()
        if not approver:
            raise ApproverNotConfigured("no approver")
        return approver

    def _adjust(self, owner: str, leave_type: str, delta: int) -> None:
        if leave_type not in ("annual", "sick"):
            return
        bal = self.balances.get(owner)
        if bal is None:
            if delta > 0:
                raise InsufficientLeaveBalance("no balance row")
            return
        key_used = "annual_used" if leave_type == "annual" else "sick_used"
        key_total = "annual_total" if leave_type == "annual" else "sick_total"
        new_used = bal[key_used] + delta
        if new_used > bal[key_total]:
            raise InsufficientLeaveBalance("exceed")
        bal[key_used] = max(0, new_used)

    @staticmethod
    def _days(start: str, end: str) -> int:
        import datetime
        s = datetime.date.fromisoformat(start)
        e = datetime.date.fromisoformat(end)
        return (e - s).days + 1

    def _record(self, **kw) -> dict:
        base = {
            "id": kw["id"], "user_id": kw["user_id"], "leave_type": kw["leave_type"],
            "start_date": kw["start_date"], "end_date": kw["end_date"],
            "days_count": kw["days_count"], "status": kw["status"],
            "reason": kw.get("reason") or None, "approver_user_id": kw["approver_user_id"],
            "approved_at": None, "rejected_at": None, "rejected_reason": None,
            "cancelled_at": None, "idempotency_key": kw.get("idempotency_key"),
        }
        return base

    def _find_key(self, key: Optional[str]) -> Optional[dict]:
        if not key:
            return None
        for r in self.requests.values():
            if r.get("idempotency_key") == key:
                return r
        return None

    async def create_leave_request(self, *, user_id, leave_type, start_date, end_date,
                                   reason, default_approver, idempotency_key=None) -> dict:
        existing = self._find_key(idempotency_key)
        if existing is not None:
            return {"request": dict(existing), "created": False}
        approver = self._resolve(user_id, default_approver)
        rid = self._new_id()
        rec = self._record(
            id=rid, user_id=user_id, leave_type=leave_type, start_date=start_date,
            end_date=end_date, days_count=self._days(start_date, end_date),
            status="pending", reason=reason, approver_user_id=approver,
            idempotency_key=idempotency_key,
        )
        self.requests[rid] = rec
        return {"request": dict(rec), "created": True}

    async def update_leave_request(self, *, user_id, request_id, leave_type, start_date,
                                   end_date, reason, default_approver, idempotency_key=None) -> dict:
        prior = self._find_key(idempotency_key)
        if prior is not None and prior["id"] != request_id:
            return {"request": dict(prior), "mode": "replaced", "replaced_request": None}
        rec = self.requests.get(request_id)
        if rec is None:
            raise LeaveRequestNotFound(request_id)
        if rec["user_id"] != user_id:
            raise LeaveRequestForbidden("not owner")
        if rec["status"] == "pending":
            rec["leave_type"] = leave_type
            rec["start_date"] = start_date
            rec["end_date"] = end_date
            rec["days_count"] = self._days(start_date, end_date)
            rec["reason"] = reason or None
            return {"request": dict(rec), "mode": "updated", "replaced_request": None}
        if rec["status"] == "approved":
            self._adjust(rec["user_id"], rec["leave_type"], -rec["days_count"])
            rec["status"] = "cancelled"
            rec["cancelled_at"] = "now"
            old = dict(rec)
            approver = self._resolve(user_id, default_approver)
            rid = self._new_id()
            new = self._record(
                id=rid, user_id=user_id, leave_type=leave_type, start_date=start_date,
                end_date=end_date, days_count=self._days(start_date, end_date),
                status="pending", reason=reason, approver_user_id=approver,
                idempotency_key=idempotency_key,
            )
            self.requests[rid] = new
            return {"request": dict(new), "mode": "replaced", "replaced_request": old}
        raise LeaveRequestConflict(rec["status"])

    async def cancel_leave_request(self, *, user_id, request_id) -> dict:
        rec = self.requests.get(request_id)
        if rec is None:
            raise LeaveRequestNotFound(request_id)
        if rec["user_id"] != user_id:
            raise LeaveRequestForbidden("not owner")
        if rec["status"] in ("cancelled", "rejected"):
            return {"request": dict(rec), "changed": False}
        if rec["status"] == "approved":
            self._adjust(rec["user_id"], rec["leave_type"], -rec["days_count"])
        rec["status"] = "cancelled"
        rec["cancelled_at"] = "now"
        return {"request": dict(rec), "changed": True}

    async def list_pending_approval(self, approver_user_id) -> list:
        return [
            dict(r) for r in self.requests.values()
            if r["approver_user_id"] == approver_user_id and r["status"] == "pending"
        ]

    async def update_leave_status(self, *, request_id, approver_user_id, action, reason=None) -> dict:
        rec = self.requests.get(request_id)
        if rec is None:
            raise LeaveRequestNotFound(request_id)
        if rec["approver_user_id"] != approver_user_id:
            raise LeaveRequestForbidden("wrong approver")
        if rec["status"] != "pending":
            raise LeaveRequestConflict(rec["status"])
        if action == "approve":
            self._adjust(rec["user_id"], rec["leave_type"], rec["days_count"])
            rec["status"] = "approved"
            rec["approved_at"] = "now"
        elif action == "reject":
            rec["status"] = "rejected"
            rec["rejected_at"] = "now"
            rec["rejected_reason"] = reason or None
        else:
            raise ValueError(action)
        return {"request": dict(rec)}


class RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def publish(self, subject: str, payload: dict) -> None:
        self.events.append((subject, payload))

    def subjects(self) -> list[str]:
        return [s for s, _ in self.events]


class FailingPublisher:
    async def publish(self, subject: str, payload: dict) -> None:
        raise RuntimeError("NATS down")


def _settings(default_approver: str = "") -> HrSettings:
    return HrSettings(
        host="0.0.0.0", port=8004, log_level="INFO", database_url="",
        internal_token="", auto_provision_leave_balance=True,
        default_annual_leave=12, default_sick_leave=10,
        nats_url="nats://nats:4222", nats_jetstream_enabled=True,
        user_events_enabled=False, default_approver=default_approver,
        app_stage="production",
    )


@pytest.fixture
def ctx():
    repo = FakeLeaveWriteRepo()
    publisher = RecordingPublisher()
    settings = _settings()

    app.dependency_overrides[get_write_repo] = lambda: repo
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_publisher] = lambda: publisher
    client = TestClient(app)
    try:
        yield client, repo, publisher, settings
    finally:
        app.dependency_overrides.clear()


def _set_default_approver(client, value):
    # đổi settings default_approver giữa test
    from app.api import routes as routes_mod  # noqa: F401
    app.dependency_overrides[get_settings] = lambda: _settings(default_approver=value)


# ─────────────────────────────── CREATE ───────────────────────────────
def test_create_success_resolves_manager_and_publishes(ctx):
    client, repo, pub, _ = ctx
    repo.managers[EMP] = MANAGER
    r = client.post("/hr/leave-requests", json={
        "user_id": EMP, "leave_type": "annual",
        "start_date": "2026-07-01", "end_date": "2026-07-03", "reason": "nghỉ",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["approver_user_id"] == MANAGER
    assert body["days_count"] == 3
    assert pub.subjects() == ["hr.leave_request.created"]
    assert pub.events[0][1]["approver_user_id"] == MANAGER


def test_create_falls_back_to_default_approver(ctx):
    client, repo, pub, _ = ctx
    _set_default_approver(client, DEFAULT_APPROVER)  # no manager -> default
    r = client.post("/hr/leave-requests", json={
        "user_id": EMP, "leave_type": "sick",
        "start_date": "2026-07-01", "end_date": "2026-07-01",
    })
    assert r.status_code == 201
    assert r.json()["approver_user_id"] == DEFAULT_APPROVER


def test_create_no_approver_returns_422_and_no_event(ctx):
    client, repo, pub, _ = ctx  # no manager, default_approver=""
    r = client.post("/hr/leave-requests", json={
        "user_id": EMP, "leave_type": "annual",
        "start_date": "2026-07-01", "end_date": "2026-07-02",
    })
    assert r.status_code == 422
    assert pub.events == []


def test_create_start_after_end_returns_422(ctx):
    client, repo, pub, _ = ctx
    repo.managers[EMP] = MANAGER
    r = client.post("/hr/leave-requests", json={
        "user_id": EMP, "leave_type": "annual",
        "start_date": "2026-07-05", "end_date": "2026-07-01",
    })
    assert r.status_code == 422
    assert pub.events == []


def test_create_bad_date_format_returns_422(ctx):
    client, repo, pub, _ = ctx
    repo.managers[EMP] = MANAGER
    r = client.post("/hr/leave-requests", json={
        "user_id": EMP, "leave_type": "annual",
        "start_date": "01/07/2026", "end_date": "2026-07-02",
    })
    assert r.status_code == 422


def test_create_invalid_leave_type_returns_422(ctx):
    client, repo, pub, _ = ctx
    repo.managers[EMP] = MANAGER
    r = client.post("/hr/leave-requests", json={
        "user_id": EMP, "leave_type": "unpaid",
        "start_date": "2026-07-01", "end_date": "2026-07-02",
    })
    assert r.status_code == 422  # Literal validation


def test_create_idempotent_same_key_no_duplicate(ctx):
    client, repo, pub, _ = ctx
    repo.managers[EMP] = MANAGER
    payload = {
        "user_id": EMP, "leave_type": "annual",
        "start_date": "2026-07-01", "end_date": "2026-07-02",
        "idempotency_key": "key-abc",
    }
    r1 = client.post("/hr/leave-requests", json=payload)
    r2 = client.post("/hr/leave-requests", json=payload)
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]
    assert len(repo.requests) == 1
    # event created CHỈ publish 1 lần (retry không bắn lại -> không báo trùng)
    assert pub.subjects() == ["hr.leave_request.created"]


# ─────────────────────────────── UPDATE ───────────────────────────────
def _create(client, repo, leave_type="annual", start="2026-07-01", end="2026-07-02", key=None):
    repo.managers.setdefault(EMP, MANAGER)
    body = {"user_id": EMP, "leave_type": leave_type, "start_date": start, "end_date": end}
    if key:
        body["idempotency_key"] = key
    return client.post("/hr/leave-requests", json=body).json()


def test_update_pending_in_place(ctx):
    client, repo, pub, _ = ctx
    rid = _create(client, repo)["id"]
    r = client.patch(f"/hr/leave-requests/{rid}", json={
        "user_id": EMP, "leave_type": "annual",
        "start_date": "2026-07-01", "end_date": "2026-07-05",
    })
    assert r.status_code == 200, r.text
    assert r.json()["id"] == rid
    assert r.json()["days_count"] == 5
    assert "hr.leave_request.updated" in pub.subjects()


def test_update_approved_cancels_refunds_and_recreates(ctx):
    client, repo, pub, _ = ctx
    repo.seed_balance(EMP, annual_total=12, annual_used=0)
    rid = _create(client, repo, start="2026-07-01", end="2026-07-02")["id"]  # 2 days
    # approve -> deduct 2
    client.post(f"/hr/leave-requests/{rid}/approve", json={"approver_user_id": MANAGER})
    assert repo.balances[EMP]["annual_used"] == 2
    # edit approved -> refund 2, cancel old, create new pending
    r = client.patch(f"/hr/leave-requests/{rid}", json={
        "user_id": EMP, "leave_type": "annual",
        "start_date": "2026-08-01", "end_date": "2026-08-01",
    })
    assert r.status_code == 200
    new_id = r.json()["id"]
    assert new_id != rid
    assert r.json()["status"] == "pending"
    assert repo.requests[rid]["status"] == "cancelled"
    assert repo.balances[EMP]["annual_used"] == 0  # refunded
    subs = pub.subjects()
    assert "hr.leave_request.cancelled" in subs and "hr.leave_request.created" in subs


def test_update_not_owner_403(ctx):
    client, repo, pub, _ = ctx
    rid = _create(client, repo)["id"]
    r = client.patch(f"/hr/leave-requests/{rid}", json={
        "user_id": OTHER, "leave_type": "annual",
        "start_date": "2026-07-01", "end_date": "2026-07-02",
    })
    assert r.status_code == 403


def test_update_not_found_404(ctx):
    client, repo, pub, _ = ctx
    r = client.patch("/hr/leave-requests/nope", json={
        "user_id": EMP, "leave_type": "annual",
        "start_date": "2026-07-01", "end_date": "2026-07-02",
    })
    assert r.status_code == 404


def test_update_rejected_409(ctx):
    client, repo, pub, _ = ctx
    rid = _create(client, repo)["id"]
    client.post(f"/hr/leave-requests/{rid}/reject", json={"approver_user_id": MANAGER, "reason": "x"})
    r = client.patch(f"/hr/leave-requests/{rid}", json={
        "user_id": EMP, "leave_type": "annual",
        "start_date": "2026-07-01", "end_date": "2026-07-02",
    })
    assert r.status_code == 409


# ─────────────────────────────── CANCEL ───────────────────────────────
def test_cancel_pending(ctx):
    client, repo, pub, _ = ctx
    rid = _create(client, repo)["id"]
    r = client.post(f"/hr/leave-requests/{rid}/cancel", json={"user_id": EMP})
    assert r.status_code == 200
    assert repo.requests[rid]["status"] == "cancelled"
    assert "hr.leave_request.cancelled" in pub.subjects()


def test_cancel_approved_refunds(ctx):
    client, repo, pub, _ = ctx
    repo.seed_balance(EMP, annual_used=0)
    rid = _create(client, repo, start="2026-07-01", end="2026-07-03")["id"]  # 3 days
    client.post(f"/hr/leave-requests/{rid}/approve", json={"approver_user_id": MANAGER})
    assert repo.balances[EMP]["annual_used"] == 3
    r = client.post(f"/hr/leave-requests/{rid}/cancel", json={"user_id": EMP})
    assert r.status_code == 200
    assert repo.balances[EMP]["annual_used"] == 0


def test_cancel_not_owner_403(ctx):
    client, repo, pub, _ = ctx
    rid = _create(client, repo)["id"]
    r = client.post(f"/hr/leave-requests/{rid}/cancel", json={"user_id": OTHER})
    assert r.status_code == 403


def test_cancel_not_found_404(ctx):
    client, repo, pub, _ = ctx
    r = client.post("/hr/leave-requests/nope/cancel", json={"user_id": EMP})
    assert r.status_code == 404


def test_cancel_already_cancelled_idempotent_no_event(ctx):
    client, repo, pub, _ = ctx
    rid = _create(client, repo)["id"]
    client.post(f"/hr/leave-requests/{rid}/cancel", json={"user_id": EMP})
    pub.events.clear()
    r = client.post(f"/hr/leave-requests/{rid}/cancel", json={"user_id": EMP})
    assert r.status_code == 200
    assert pub.events == []  # no-op idempotent -> không bắn event


# ─────────────────────────── APPROVE / REJECT ──────────────────────────
def test_approve_deducts_annual(ctx):
    client, repo, pub, _ = ctx
    repo.seed_balance(EMP, annual_total=12, annual_used=1)
    rid = _create(client, repo, start="2026-07-01", end="2026-07-02")["id"]
    r = client.post(f"/hr/leave-requests/{rid}/approve", json={"approver_user_id": MANAGER})
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    assert repo.balances[EMP]["annual_used"] == 3
    assert "hr.leave_request.approved" in pub.subjects()


def test_approve_personal_no_balance_change(ctx):
    client, repo, pub, _ = ctx
    repo.seed_balance(EMP, annual_used=0)
    rid = _create(client, repo, leave_type="personal", start="2026-07-01", end="2026-07-02")["id"]
    r = client.post(f"/hr/leave-requests/{rid}/approve", json={"approver_user_id": MANAGER})
    assert r.status_code == 200
    assert repo.balances[EMP]["annual_used"] == 0


def test_approve_insufficient_balance_409_keeps_pending_no_event(ctx):
    client, repo, pub, _ = ctx
    repo.seed_balance(EMP, annual_total=12, annual_used=11)
    rid = _create(client, repo, start="2026-07-01", end="2026-07-03")["id"]  # 3 days > 1 left
    pub.events.clear()
    r = client.post(f"/hr/leave-requests/{rid}/approve", json={"approver_user_id": MANAGER})
    assert r.status_code == 409
    assert repo.requests[rid]["status"] == "pending"   # đơn KHÔNG mất, giữ pending
    assert repo.balances[EMP]["annual_used"] == 11      # balance không đổi
    assert pub.events == []                             # không publish approved


def test_approve_wrong_approver_403(ctx):
    client, repo, pub, _ = ctx
    rid = _create(client, repo)["id"]
    r = client.post(f"/hr/leave-requests/{rid}/approve", json={"approver_user_id": OTHER})
    assert r.status_code == 403


def test_approve_already_approved_409(ctx):
    client, repo, pub, _ = ctx
    repo.seed_balance(EMP, annual_used=0)
    rid = _create(client, repo)["id"]
    client.post(f"/hr/leave-requests/{rid}/approve", json={"approver_user_id": MANAGER})
    r = client.post(f"/hr/leave-requests/{rid}/approve", json={"approver_user_id": MANAGER})
    assert r.status_code == 409


def test_reject_sets_reason_and_publishes(ctx):
    client, repo, pub, _ = ctx
    rid = _create(client, repo)["id"]
    r = client.post(f"/hr/leave-requests/{rid}/reject",
                    json={"approver_user_id": MANAGER, "reason": "bận dự án"})
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    assert r.json()["rejected_reason"] == "bận dự án"
    ev = [p for s, p in pub.events if s == "hr.leave_request.rejected"]
    assert ev and ev[0]["rejected_reason"] == "bận dự án"


# ──────────────────────── PENDING-APPROVAL (PULL) ──────────────────────
def test_pending_approval_lists_only_relevant(ctx):
    client, repo, pub, _ = ctx
    repo.managers[EMP] = MANAGER
    repo.managers[OTHER] = "someone-else"
    a = _create(client, repo)["id"]
    # đơn của OTHER -> approver khác
    client.post("/hr/leave-requests", json={
        "user_id": OTHER, "leave_type": "annual",
        "start_date": "2026-07-01", "end_date": "2026-07-02",
    })
    # 1 đơn của EMP rồi reject -> không còn pending
    b = _create(client, repo)["id"]
    client.post(f"/hr/leave-requests/{b}/reject", json={"approver_user_id": MANAGER})

    r = client.get("/hr/leave-requests/pending-approval", params={"approver_user_id": MANAGER})
    assert r.status_code == 200
    body = r.json()
    ids = [it["id"] for it in body["items"]]
    assert ids == [a]
    assert body["count"] == 1
