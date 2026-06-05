from datetime import UTC, datetime, timedelta

import pytest

from app.infrastructure.db.mock_document_access_repo import InMemoryDocumentAccessRepository
from app.infrastructure.messaging.notification_service import NotificationService


@pytest.mark.asyncio
async def test_doc_access_event_upserts_deletes_and_ignores_stale_events():
    from app.infrastructure.messaging.nats_events import QueryNatsEventHandler

    repo = InMemoryDocumentAccessRepository()
    handler = QueryNatsEventHandler(document_access_repo=repo)
    now = datetime.now(UTC)
    document_id = "eeeeeeee-0001-4000-8000-000000000001"

    await handler.handle_doc_access(
        {
            "event_id": "event-new",
            "occurred_at": now.isoformat(),
            "doc_id": document_id,
            "classification": "secret",
            "allowed_departments": ["Finance"],
            "allowed_user_ids": [],
            "deleted": False,
        }
    )

    allowed = await repo.get_allowed_doc_ids(
        user_id="22222222-2222-4222-8222-222222222222",
        role="user",
        department="Finance",
    )
    assert document_id in allowed

    await handler.handle_doc_access(
        {
            "event_id": "event-stale",
            "occurred_at": (now - timedelta(minutes=1)).isoformat(),
            "doc_id": document_id,
            "classification": "top_secret",
            "allowed_departments": [],
            "allowed_user_ids": ["someone-else"],
            "deleted": False,
        }
    )

    allowed_after_stale = await repo.get_allowed_doc_ids(
        user_id="22222222-2222-4222-8222-222222222222",
        role="user",
        department="Finance",
    )
    assert document_id in allowed_after_stale

    await handler.handle_doc_access(
        {
            "event_id": "event-delete",
            "occurred_at": (now + timedelta(minutes=1)).isoformat(),
            "doc_id": document_id,
            "classification": "secret",
            "allowed_departments": ["Finance"],
            "allowed_user_ids": [],
            "deleted": True,
        }
    )

    allowed_after_delete = await repo.get_allowed_doc_ids(
        user_id="22222222-2222-4222-8222-222222222222",
        role="user",
        department="Finance",
    )
    assert document_id not in allowed_after_delete


@pytest.mark.asyncio
async def test_doc_access_event_passes_datetime_to_repository():
    from app.infrastructure.messaging.nats_events import QueryNatsEventHandler

    class CapturingDocumentAccessRepository:
        def __init__(self) -> None:
            self.occurred_at = None

        async def get_allowed_doc_ids(self, user_id: str, role: str, department: str):
            return []

        async def upsert_access(
            self,
            document_id: str,
            classification: str,
            allowed_departments: list[str],
            allowed_user_ids: list[str],
            occurred_at=None,
        ) -> None:
            self.occurred_at = occurred_at

        async def delete_access(self, document_id: str) -> None:
            pass

    repo = CapturingDocumentAccessRepository()
    handler = QueryNatsEventHandler(document_access_repo=repo)
    occurred_at = datetime.now(UTC)

    await handler.handle_doc_access(
        {
            "event_id": "event-datetime",
            "occurred_at": occurred_at.isoformat(),
            "doc_id": "eeeeeeee-0003-4000-8000-000000000003",
            "classification": "internal",
            "allowed_departments": [],
            "allowed_user_ids": [],
            "deleted": False,
        }
    )

    assert isinstance(repo.occurred_at, datetime)
    assert repo.occurred_at == occurred_at


@pytest.mark.asyncio
async def test_notify_doc_new_event_is_deduplicated():
    from app.infrastructure.messaging.nats_events import QueryNatsEventHandler
    from app.interfaces.api.dependencies import get_connection_manager, get_notification_repo

    repo = get_notification_repo()
    service = NotificationService(
        repository=repo,
        connection_manager=get_connection_manager(),
    )
    handler = QueryNatsEventHandler(notification_service=service)

    payload = {
        "event_id": "notify-1",
        "occurred_at": datetime.now(UTC).isoformat(),
        "doc_id": "dddddddd-0002-4000-8000-000000000002",
        "document_name": "Internal Handbook.pdf",
        "classification": "internal",
        "allowed_departments": [],
        "allowed_user_ids": [],
    }

    delivered_first = await handler.handle_notify_doc_new(payload)
    delivered_second = await handler.handle_notify_doc_new(payload)

    assert delivered_first
    assert delivered_second == []
    assert await repo.unread_count("11111111-1111-4111-8111-111111111111") == 1


def test_nats_mode_uses_postgres_repository_adapters(monkeypatch):
    from app.infrastructure.config import get_settings
    from app.infrastructure.db.postgres_document_access_repo import PostgresDocumentAccessRepository
    from app.infrastructure.db.postgres_notification_repo import PostgresNotificationRepository
    from app.interfaces.api.dependencies import get_document_access_repo, get_notification_repo

    monkeypatch.setenv("NATS_MODE", "nats")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/query_db")
    get_settings.cache_clear()
    get_document_access_repo.cache_clear()
    get_notification_repo.cache_clear()

    assert isinstance(get_document_access_repo(), PostgresDocumentAccessRepository)
    assert isinstance(get_notification_repo(), PostgresNotificationRepository)


def test_nats_subscriber_manager_factory_respects_nats_mode(monkeypatch):
    from app.infrastructure.config import get_settings
    from app.infrastructure.messaging.nats_subscriber import NatsSubscriberManager
    from app.interfaces.api.dependencies import get_nats_subscriber_manager

    monkeypatch.setenv("NATS_MODE", "mock")
    get_settings.cache_clear()
    get_nats_subscriber_manager.cache_clear()
    assert get_nats_subscriber_manager() is None

    monkeypatch.setenv("NATS_MODE", "nats")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/query_db")
    get_settings.cache_clear()
    get_nats_subscriber_manager.cache_clear()
    manager = get_nats_subscriber_manager()
    assert isinstance(manager, NatsSubscriberManager)


@pytest.mark.asyncio
async def test_nats_subscriber_manager_subscribes_and_acks_messages():
    from types import SimpleNamespace

    from app.infrastructure.messaging.nats_subscriber import NatsSubscriberManager

    class FakeMsg:
        def __init__(self, data: bytes) -> None:
            self.data = data
            self.acked = False
            self.nacked = False

        async def ack(self):
            self.acked = True

        async def nak(self):
            self.nacked = True

    class FakeJetStream:
        def __init__(self) -> None:
            self.subscriptions = {}

        async def subscribe(self, subject, durable, cb):
            self.subscriptions[subject] = {"durable": durable, "cb": cb}

    class FakeConnection:
        def __init__(self) -> None:
            self.js = FakeJetStream()
            self.drained = False

        def jetstream(self):
            return self.js

        async def drain(self):
            self.drained = True

    class FakeNatsModule:
        def __init__(self) -> None:
            self.connection = FakeConnection()

        async def connect(self, url):
            self.url = url
            return self.connection

    class FakeHandler:
        def __init__(self) -> None:
            self.doc_access_calls = []
            self.notify_calls = []
            self.fail_doc_access = False

        async def handle_doc_access(self, payload):
            if self.fail_doc_access:
                raise RuntimeError("temporary db failure")
            self.doc_access_calls.append(payload)

        async def handle_notify_doc_new(self, payload):
            self.notify_calls.append(payload)

    fake_nats = FakeNatsModule()
    handler = FakeHandler()
    settings = SimpleNamespace(nats_url="nats://test")
    manager = NatsSubscriberManager(settings, handler, nats_module=fake_nats)

    await manager.start()

    assert fake_nats.url == "nats://test"
    assert fake_nats.connection.js.subscriptions["doc.access"]["durable"] == "QUERY_SERVICE_DOC_ACCESS"
    assert fake_nats.connection.js.subscriptions["notify.doc_new"]["durable"] == "QUERY_SERVICE_NOTIFY_DOC_NEW"

    valid_msg = FakeMsg(
        b'{"doc_id":"doc-1","classification":"internal","allowed_departments":[],"allowed_user_ids":[],"deleted":false}'
    )
    await fake_nats.connection.js.subscriptions["doc.access"]["cb"](valid_msg)
    assert valid_msg.acked is True
    assert handler.doc_access_calls[0]["doc_id"] == "doc-1"

    invalid_msg = FakeMsg(b'{"doc_id":""}')
    await fake_nats.connection.js.subscriptions["doc.access"]["cb"](invalid_msg)
    assert invalid_msg.acked is True

    handler.fail_doc_access = True
    retry_msg = FakeMsg(
        b'{"doc_id":"doc-2","classification":"internal","allowed_departments":[],"allowed_user_ids":[],"deleted":false}'
    )
    await fake_nats.connection.js.subscriptions["doc.access"]["cb"](retry_msg)
    assert retry_msg.nacked is True

    await manager.stop()
    assert fake_nats.connection.drained is True
