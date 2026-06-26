"""Tests for notification endpoints (history, unread-count, mark-read, dev mock)."""

import pytest
from httpx import AsyncClient

from tests.conftest import HR_USER_ID, ADMIN_USER_ID


async def _seed_notification(user_id: str, doc_id: str = "doc-001", is_read: bool = False) -> str:
    """Directly seed a notification into the mock repo and return its ID."""
    from app.interfaces.api.dependencies import get_notification_repo

    # save() nhận field rời (user_id, event, message, doc_id) + trả Notification mới
    # (id + is_read=False). Muốn is_read=True thì mark_read sau khi tạo.
    repo = get_notification_repo()
    saved = await repo.save(
        user_id=user_id,
        event="doc_new",
        message=f"New document {doc_id} indexed",
        doc_id=doc_id,
    )
    if is_read:
        await repo.mark_read(saved.id)
    return saved.id


# ---------------------------------------------------------------------------
# GET /notifications/history
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notifications_history_empty(hr_client: AsyncClient):
    r = await hr_client.get("/notifications/history")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_notifications_history_returns_own_items(hr_client: AsyncClient):
    await _seed_notification(HR_USER_ID, "doc-A")
    await _seed_notification(HR_USER_ID, "doc-B")

    r = await hr_client.get("/notifications/history")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    ids = {item["doc_id"] for item in body["items"]}
    assert "doc-A" in ids
    assert "doc-B" in ids


@pytest.mark.asyncio
async def test_notifications_history_unread_only_filter(hr_client: AsyncClient):
    await _seed_notification(HR_USER_ID, "doc-read", is_read=True)
    await _seed_notification(HR_USER_ID, "doc-unread", is_read=False)

    r = await hr_client.get("/notifications/history", params={"unread_only": True})
    body = r.json()
    assert all(not item["is_read"] for item in body["items"])
    assert body["total"] == 1


@pytest.mark.asyncio
async def test_notifications_history_pagination(hr_client: AsyncClient):
    for i in range(5):
        await _seed_notification(HR_USER_ID, f"doc-{i:02d}")

    r1 = await hr_client.get("/notifications/history", params={"limit": 2, "offset": 0})
    r2 = await hr_client.get("/notifications/history", params={"limit": 2, "offset": 2})
    assert len(r1.json()["items"]) == 2
    assert len(r2.json()["items"]) == 2
    ids1 = {i["id"] for i in r1.json()["items"]}
    ids2 = {i["id"] for i in r2.json()["items"]}
    assert ids1.isdisjoint(ids2)


@pytest.mark.asyncio
async def test_notifications_isolated_per_user(hr_client: AsyncClient, finance_client: AsyncClient):
    from tests.conftest import FINANCE_USER_ID
    await _seed_notification(HR_USER_ID, "hr-doc")
    await _seed_notification(FINANCE_USER_ID, "fin-doc")

    hr_items = (await hr_client.get("/notifications/history")).json()["items"]
    fin_items = (await finance_client.get("/notifications/history")).json()["items"]

    assert all(i["doc_id"] == "hr-doc" for i in hr_items)
    assert all(i["doc_id"] == "fin-doc" for i in fin_items)


# ---------------------------------------------------------------------------
# GET /notifications/unread-count
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unread_count_zero_initially(hr_client: AsyncClient):
    r = await hr_client.get("/notifications/unread-count")
    assert r.status_code == 200
    assert r.json()["unread"] == 0


@pytest.mark.asyncio
async def test_unread_count_increments(hr_client: AsyncClient):
    await _seed_notification(HR_USER_ID, "doc-1")
    await _seed_notification(HR_USER_ID, "doc-2")

    r = await hr_client.get("/notifications/unread-count")
    assert r.json()["unread"] == 2


@pytest.mark.asyncio
async def test_unread_count_excludes_read(hr_client: AsyncClient):
    await _seed_notification(HR_USER_ID, "doc-read", is_read=True)
    await _seed_notification(HR_USER_ID, "doc-unread", is_read=False)

    r = await hr_client.get("/notifications/unread-count")
    assert r.json()["unread"] == 1


# ---------------------------------------------------------------------------
# POST /notifications/{id}/read
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_notification_read(hr_client: AsyncClient):
    nid = await _seed_notification(HR_USER_ID, "doc-mark")

    r = await hr_client.post(f"/notifications/{nid}/read")
    assert r.status_code == 200
    assert r.json()["is_read"] is True


@pytest.mark.asyncio
async def test_mark_read_not_found_returns_404(hr_client: AsyncClient):
    r = await hr_client.post("/notifications/nonexistent-id/read")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_mark_read_wrong_user_returns_404(hr_client: AsyncClient):
    """A user cannot mark another user's notification as read."""
    from tests.conftest import FINANCE_USER_ID
    nid = await _seed_notification(FINANCE_USER_ID, "fin-doc")

    r = await hr_client.post(f"/notifications/{nid}/read")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /notifications/{id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_notification_removes_it(hr_client: AsyncClient):
    nid = await _seed_notification(HR_USER_ID, "doc-del")

    r = await hr_client.delete(f"/notifications/{nid}")
    assert r.status_code == 204

    # Sau khi xóa, không còn trong history (không hiện lại khi fetch lại)
    body = (await hr_client.get("/notifications/history")).json()
    assert all(item["id"] != nid for item in body["items"])
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_delete_notification_not_found_returns_404(hr_client: AsyncClient):
    r = await hr_client.delete("/notifications/nonexistent-id")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_notification_wrong_user_returns_404(hr_client: AsyncClient):
    """A user cannot delete another user's notification."""
    from tests.conftest import FINANCE_USER_ID
    nid = await _seed_notification(FINANCE_USER_ID, "fin-doc")

    r = await hr_client.delete(f"/notifications/{nid}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /dev/mock-notifications/doc-new  (admin + ENABLE_DEV_ENDPOINTS)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dev_doc_new_creates_notification(admin_client: AsyncClient):
    payload = {
        "doc_id": "dev-doc-001",
        "document_name": "Dev Test Doc.pdf",
        "classification": "internal",
        "allowed_departments": [],
        "allowed_user_ids": [ADMIN_USER_ID],
    }
    r = await admin_client.post("/dev/mock-notifications/doc-new", json=payload)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_dev_doc_new_requires_admin(hr_client: AsyncClient):
    payload = {
        "doc_id": "dev-doc-002",
        "document_name": "Test.pdf",
        "classification": "public",
    }
    r = await hr_client.post("/dev/mock-notifications/doc-new", json=payload)
    assert r.status_code == 403
