"""Test Leave WRITE REST router (query-service) — chứng minh:
- user_id/approver_user_id LẤY TỪ JWT (không tin client),
- forward đúng sang hr-service,
- map lỗi nghiệp vụ hr (403/404/409/422) nguyên trạng.

Dùng fake HRLeaveClient (override dependency) -> không cần hr-service thật.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.interfaces.api.dependencies import get_hr_leave_client
from app.interfaces.api.main import app
from tests.conftest import HR_USER_ID


class FakeHRLeaveClient:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.create_ret = (201, {"id": "r1", "status": "pending", "approver_user_id": "mgr"})
        self.cancel_ret = (200, {"id": "r1", "status": "cancelled"})
        self.pending_ret = (200, {"items": [], "count": 0})
        self.decide_ret = (200, {"id": "r1", "status": "approved"})

    async def create(self, **kw):
        self.calls.append(("create", kw))
        return self.create_ret

    async def cancel(self, **kw):
        self.calls.append(("cancel", kw))
        return self.cancel_ret

    async def list_pending_approval(self, **kw):
        self.calls.append(("pending", kw))
        return self.pending_ret

    async def decide(self, **kw):
        self.calls.append(("decide", kw))
        return self.decide_ret


@pytest.fixture
def fake_hr():
    fake = FakeHRLeaveClient()
    app.dependency_overrides[get_hr_leave_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_hr_leave_client, None)


@pytest.mark.asyncio
async def test_create_injects_user_id_from_jwt(hr_client: AsyncClient, fake_hr):
    r = await hr_client.post("/leave-requests", json={
        "leave_type": "annual", "start_date": "2026-09-01", "end_date": "2026-09-02",
        "reason": "nghỉ",
    })
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "pending"
    op, kw = fake_hr.calls[0]
    assert op == "create"
    assert kw["user_id"] == HR_USER_ID          # từ JWT, KHÔNG từ body
    assert kw["leave_type"] == "annual"
    assert kw["idempotency_key"]                # tự sinh nếu client không gửi


@pytest.mark.asyncio
async def test_create_forwards_client_idempotency_key(hr_client: AsyncClient, fake_hr):
    await hr_client.post("/leave-requests", json={
        "leave_type": "sick", "start_date": "2026-09-01", "end_date": "2026-09-01",
        "idempotency_key": "key-xyz",
    })
    assert fake_hr.calls[0][1]["idempotency_key"] == "key-xyz"


@pytest.mark.asyncio
async def test_create_rejects_bad_leave_type(hr_client: AsyncClient, fake_hr):
    r = await hr_client.post("/leave-requests", json={
        "leave_type": "unpaid", "start_date": "2026-09-01", "end_date": "2026-09-01",
    })
    assert r.status_code == 422  # Literal validation, chưa gọi hr
    assert fake_hr.calls == []


@pytest.mark.asyncio
async def test_create_maps_hr_422(hr_client: AsyncClient, fake_hr):
    fake_hr.create_ret = (422, {"detail": "approver chưa cấu hình"})
    r = await hr_client.post("/leave-requests", json={
        "leave_type": "annual", "start_date": "2026-09-01", "end_date": "2026-09-02",
    })
    assert r.status_code == 422
    assert "approver" in r.json()["detail"]


@pytest.mark.asyncio
async def test_cancel_injects_user_id(hr_client: AsyncClient, fake_hr):
    r = await hr_client.post("/leave-requests/req-9/cancel")
    assert r.status_code == 200
    op, kw = fake_hr.calls[0]
    assert op == "cancel" and kw["user_id"] == HR_USER_ID and kw["request_id"] == "req-9"


@pytest.mark.asyncio
async def test_pending_approval_uses_jwt_as_approver(hr_client: AsyncClient, fake_hr):
    r = await hr_client.get("/leave-requests/pending-approval")
    assert r.status_code == 200
    op, kw = fake_hr.calls[0]
    assert op == "pending" and kw["approver_user_id"] == HR_USER_ID


@pytest.mark.asyncio
async def test_approve_uses_jwt_as_approver(hr_client: AsyncClient, fake_hr):
    r = await hr_client.post("/leave-requests/req-9/approve")
    assert r.status_code == 200
    op, kw = fake_hr.calls[0]
    assert op == "decide" and kw["action"] == "approve" and kw["approver_user_id"] == HR_USER_ID


@pytest.mark.asyncio
async def test_reject_forwards_reason(hr_client: AsyncClient, fake_hr):
    fake_hr.decide_ret = (200, {"id": "r1", "status": "rejected"})
    r = await hr_client.post("/leave-requests/req-9/reject", json={"reason": "bận dự án"})
    assert r.status_code == 200
    op, kw = fake_hr.calls[0]
    assert op == "decide" and kw["action"] == "reject" and kw["reason"] == "bận dự án"


@pytest.mark.asyncio
async def test_approve_maps_hr_403(hr_client: AsyncClient, fake_hr):
    fake_hr.decide_ret = (403, {"detail": "không phải người duyệt"})
    r = await hr_client.post("/leave-requests/req-9/approve")
    assert r.status_code == 403
