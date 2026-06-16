"""Regression tests: doc_new notifications must respect account_type/role/classification,
not just connection presence. Covers the bug where account_type was never passed to
can_access_document(), causing external-account users to be treated as internal."""

import pytest

from app.application.ports import AuthenticatedUser
from app.infrastructure.db.mock_notification_repo import InMemoryNotificationRepository
from app.infrastructure.messaging.notification_service import DocNewEvent, NotificationService
from app.infrastructure.sse.connection_manager import ConnectionManager


def _user(user_id: str, role: str, account_type: str = "internal", department: str = "") -> AuthenticatedUser:
    return AuthenticatedUser(
        id=user_id,
        email=f"{user_id}@example.com",
        role=role,
        account_type=account_type,
        department=department,
    )


@pytest.fixture
async def service():
    manager = ConnectionManager()
    svc = NotificationService(repository=InMemoryNotificationRepository(), connection_manager=manager)
    return svc, manager


@pytest.mark.asyncio
async def test_external_user_not_notified_for_internal_doc(service):
    svc, manager = service
    external_user = _user("ext-1", role="user", account_type="external")
    await manager.connect(external_user)

    event = DocNewEvent(doc_id="d1", document_name="Internal Doc", classification="internal")
    delivered = await svc.publish_doc_new(event)

    assert delivered == []


@pytest.mark.asyncio
async def test_external_user_notified_for_public_doc(service):
    svc, manager = service
    external_user = _user("ext-1", role="user", account_type="external")
    await manager.connect(external_user)

    event = DocNewEvent(doc_id="d2", document_name="Public Doc", classification="public")
    delivered = await svc.publish_doc_new(event)

    assert [n.user_id for n in delivered] == ["ext-1"]


@pytest.mark.asyncio
async def test_internal_user_notified_for_internal_doc(service):
    svc, manager = service
    internal_user = _user("int-1", role="user", account_type="internal")
    await manager.connect(internal_user)

    event = DocNewEvent(doc_id="d3", document_name="Internal Doc", classification="internal")
    delivered = await svc.publish_doc_new(event)

    assert [n.user_id for n in delivered] == ["int-1"]
