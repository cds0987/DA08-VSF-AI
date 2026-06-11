import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.application.auth import CurrentUser
from app.application.exceptions import PermissionDeniedError, StorageError, ValidationError
from app.application.use_cases.documents.common import MAX_FILE_BYTES
from app.application.use_cases.documents.delete_document_use_case import DeleteDocumentUseCase
from app.application.use_cases.documents.get_document_file_use_case import GetDocumentFileUseCase
from app.application.use_cases.documents.get_document_use_case import GetDocumentUseCase
from app.application.use_cases.documents.upload_document_use_case import UploadDocumentUseCase
from app.domain.entities.document import Document, DocumentStatus
from app.infrastructure.messaging.nats_publisher import _with_event_metadata


class InMemoryDocuments:
    def __init__(self, documents: list[Document] | None = None) -> None:
        self.documents = {document.id: document for document in documents or []}
        self.status_updates: list[tuple[str, DocumentStatus, str | None]] = []

    async def create(self, document: Document) -> Document:
        self.documents[document.id] = document
        return document

    async def get_by_id(self, document_id: str) -> Document | None:
        return self.documents.get(document_id)

    async def list_all(
        self,
        status: DocumentStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Document], int]:
        documents = list(self.documents.values())
        if status is not None:
            documents = [document for document in documents if document.status == status]
        return documents[offset : offset + limit], len(documents)

    async def update_status(
        self,
        document_id: str,
        status: DocumentStatus,
        chunk_count: int = 0,
        error: str | None = None,
    ) -> None:
        self.status_updates.append((document_id, status, error))

    async def delete(self, document_id: str) -> None:
        self.documents.pop(document_id, None)


class FakeStorage:
    def __init__(self) -> None:
        self.uploads: list[str] = []
        self.deletes: list[str] = []

    async def upload_file(self, key: str, content: bytes, content_type: str | None = None) -> None:
        self.uploads.append(key)

    def object_uri(self, key: str) -> str:
        return f"gs://rag-chatbot-docs/{key}"

    async def delete_file(self, key: str) -> None:
        self.deletes.append(key)

    async def generate_presigned_url(self, key: str, expires_in: int = 300) -> str:
        return f"https://example.test/{key}?ttl={expires_in}"


class FailingUploadStorage(FakeStorage):
    async def upload_file(self, key: str, content: bytes, content_type: str | None = None) -> None:
        raise RuntimeError("storage unavailable")


class FailingDeleteStorage(FakeStorage):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    async def delete_file(self, key: str) -> None:
        self.events.append("storage.delete")
        raise RuntimeError("storage unavailable")


class InvalidUrlStorage(FakeStorage):
    async def generate_presigned_url(self, key: str, expires_in: int = 300) -> str:
        return "not-a-browser-url"


class FakePublisher:
    def __init__(self) -> None:
        self.ingest_payloads: list[dict] = []
        self.access_payloads: list[dict] = []

    async def publish_doc_ingest(self, payload: dict) -> None:
        self.ingest_payloads.append(payload)

    async def publish_doc_access(self, payload: dict) -> None:
        self.access_payloads.append(payload)


class FakeNotifyPublisher:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.notify_payloads: list[dict] = []

    async def publish_notify_doc_new(self, payload: dict) -> None:
        self.events.append("publisher.notify")
        self.notify_payloads.append(payload)


class FakeAudit:
    def __init__(self) -> None:
        self.actions: list[str] = []

    async def log(self, action: str, **kwargs: object) -> None:
        self.actions.append(action)


def admin() -> CurrentUser:
    return CurrentUser(id=str(uuid4()), role="admin", account_type="internal", department="IT")


def document(
    classification: str = "internal",
    allowed_departments: list[str] | None = None,
    allowed_user_ids: list[str] | None = None,
    file_type: str = "pdf",
) -> Document:
    return Document(
        id=str(uuid4()),
        name="policy.pdf",
        file_type=file_type,
        gcs_key="raw/policy.pdf",
        status=DocumentStatus.INDEXED,
        uploaded_by=str(uuid4()),
        created_at=datetime.now(timezone.utc),
        classification=classification,
        allowed_departments=allowed_departments or [],
        allowed_user_ids=allowed_user_ids or [],
    )


def make_upload_case() -> tuple[UploadDocumentUseCase, InMemoryDocuments, FakePublisher, FakeAudit]:
    repo = InMemoryDocuments()
    storage = FakeStorage()
    publisher = FakePublisher()
    audit = FakeAudit()
    return UploadDocumentUseCase(repo, storage, publisher, audit), repo, publisher, audit


class OrderedDocuments(InMemoryDocuments):
    def __init__(self, documents: list[Document], events: list[str]) -> None:
        super().__init__(documents)
        self.events = events

    async def delete(self, document_id: str) -> None:
        self.events.append("repo.delete")
        await super().delete(document_id)


class OrderedPublisher(FakePublisher):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    async def publish_doc_access(self, payload: dict) -> None:
        self.events.append("publisher.access")
        await super().publish_doc_access(payload)


class OrderedAudit(FakeAudit):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    async def log(self, action: str, **kwargs: object) -> None:
        self.events.append("audit.log")
        await super().log(action, **kwargs)


def test_nats_event_metadata_is_added_to_doc_events() -> None:
    payload = _with_event_metadata("doc.ingest", {"doc_id": "doc-1"})

    assert payload["doc_id"] == "doc-1"
    assert payload["event_version"] == 1
    assert payload["event_id"]
    assert payload["occurred_at"].endswith("Z")


@pytest.mark.asyncio
async def test_status_indexed_updates_db_then_publishes_notify(monkeypatch) -> None:
    from app.infrastructure.messaging import nats_subscriber

    events: list[str] = []
    doc = document(
        classification="secret",
        allowed_departments=["HR"],
        allowed_user_ids=["user-1"],
    )

    class FakeSessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

    class FakeRepo:
        def __init__(self, session: object) -> None:
            self.session = session

        async def update_status(
            self,
            document_id: str,
            status: DocumentStatus,
            chunk_count: int = 0,
            error: str | None = None,
        ) -> None:
            events.append("repo.update_status")
            assert document_id == doc.id
            assert status == DocumentStatus.INDEXED
            assert chunk_count == 7
            assert error is None

        async def get_by_id(self, document_id: str) -> Document | None:
            events.append("repo.get_by_id")
            assert document_id == doc.id
            return doc

    class FakeMessage:
        def __init__(self) -> None:
            self.data = json.dumps(
                {
                    "event_id": str(uuid4()),
                    "event_version": 1,
                    "occurred_at": "2026-06-05T09:18:47Z",
                    "doc_id": doc.id,
                    "status": "indexed",
                    "chunk_count": 7,
                },
            ).encode("utf-8")
            self.acked = False
            self.naked = False

        async def ack(self) -> None:
            events.append("message.ack")
            self.acked = True

        async def nak(self) -> None:
            self.naked = True

    monkeypatch.setattr(nats_subscriber, "AsyncSessionLocal", lambda: FakeSessionContext())
    monkeypatch.setattr(nats_subscriber, "PostgresDocumentRepository", FakeRepo)
    publisher = FakeNotifyPublisher(events)
    message = FakeMessage()

    await nats_subscriber._handle_status_message(message, publisher)  # noqa: SLF001

    assert events == ["repo.update_status", "repo.get_by_id", "publisher.notify", "message.ack"]
    assert message.acked is True
    assert message.naked is False
    assert publisher.notify_payloads == [
        {
            "doc_id": doc.id,
            "document_name": "policy.pdf",
            "classification": "secret",
            "allowed_departments": ["HR"],
            "allowed_user_ids": ["user-1"],
        },
    ]


@pytest.mark.asyncio
async def test_upload_rejects_unsupported_extension() -> None:
    use_case, _, _, _ = make_upload_case()

    with pytest.raises(ValidationError, match="File type not supported"):
        await use_case.execute(admin(), "policy.exe", b"content", "internal")


@pytest.mark.asyncio
async def test_upload_rejects_file_over_50mb() -> None:
    use_case, _, _, _ = make_upload_case()

    with pytest.raises(ValidationError, match="File exceeds 50MB"):
        await use_case.execute(admin(), "policy.pdf", b"x" * (MAX_FILE_BYTES + 1), "internal")


@pytest.mark.asyncio
async def test_upload_rejects_invalid_classification() -> None:
    use_case, _, _, _ = make_upload_case()

    with pytest.raises(ValidationError, match="Invalid classification"):
        await use_case.execute(admin(), "policy.pdf", b"content", "confidential")


@pytest.mark.asyncio
async def test_upload_validates_secret_acl() -> None:
    use_case, _, _, _ = make_upload_case()

    with pytest.raises(ValidationError, match="allowed_departments"):
        await use_case.execute(admin(), "policy.pdf", b"content", "secret")


@pytest.mark.asyncio
async def test_upload_validates_top_secret_acl() -> None:
    use_case, _, _, _ = make_upload_case()

    with pytest.raises(ValidationError, match="allowed_user_ids"):
        await use_case.execute(admin(), "policy.pdf", b"content", "top_secret")


@pytest.mark.asyncio
async def test_upload_publishes_ingest_and_access_events() -> None:
    use_case, repo, publisher, audit = make_upload_case()

    result = await use_case.execute(
        admin(),
        "policy.pdf",
        b"content",
        "secret",
        allowed_departments=["HR"],
    )

    assert result.status == "queued"
    assert result.document_id in repo.documents
    assert next(iter(repo.documents.values())).gcs_key.startswith(f"raw/{result.document_id}/")
    assert publisher.ingest_payloads[0] == {
        "doc_id": result.document_id,
        "gcs_key": f"gs://rag-chatbot-docs/raw/{result.document_id}/policy.pdf",
        "document_name": "policy.pdf",
        "file_type": "pdf",
        "classification": "secret",
        "allowed_departments": ["HR"],
        "allowed_user_ids": [],
    }
    assert "s3_key" not in publisher.ingest_payloads[0]
    assert publisher.access_payloads[0] == {
        "doc_id": result.document_id,
        "classification": "secret",
        "allowed_departments": ["HR"],
        "allowed_user_ids": [],
        "deleted": False,
    }
    assert audit.actions == ["upload"]


@pytest.mark.asyncio
async def test_upload_wraps_storage_errors() -> None:
    use_case = UploadDocumentUseCase(
        InMemoryDocuments(),
        FailingUploadStorage(),
        FakePublisher(),
        FakeAudit(),
    )

    with pytest.raises(StorageError):
        await use_case.execute(admin(), "policy.pdf", b"content", "internal")


@pytest.mark.asyncio
async def test_file_acl_allows_matching_secret_department() -> None:
    doc = document(classification="secret", allowed_departments=["HR"])
    use_case = GetDocumentFileUseCase(InMemoryDocuments([doc]), FakeStorage())

    result = await use_case.execute(
        CurrentUser(id=str(uuid4()), role="user", account_type="internal", department="HR"),
        doc.id,
    )

    assert result.file_type == "pdf"
    assert result.expires_in == 300


@pytest.mark.asyncio
async def test_file_response_normalizes_legacy_file_type() -> None:
    doc = document(file_type=".PDF")
    use_case = GetDocumentFileUseCase(InMemoryDocuments([doc]), FakeStorage())

    result = await use_case.execute(
        CurrentUser(id=str(uuid4()), role="user", account_type="internal", department="HR"),
        doc.id,
    )

    assert result.file_type == "pdf"
    assert result.url.startswith("https://")
    assert result.expires_in == 300


@pytest.mark.asyncio
async def test_file_response_rejects_invalid_file_type() -> None:
    doc = document(file_type="exe")
    use_case = GetDocumentFileUseCase(InMemoryDocuments([doc]), FakeStorage())

    with pytest.raises(StorageError):
        await use_case.execute(
            CurrentUser(id=str(uuid4()), role="user", account_type="internal", department="HR"),
            doc.id,
        )


@pytest.mark.asyncio
async def test_file_response_rejects_invalid_signed_url() -> None:
    doc = document()
    use_case = GetDocumentFileUseCase(InMemoryDocuments([doc]), InvalidUrlStorage())

    with pytest.raises(StorageError):
        await use_case.execute(
            CurrentUser(id=str(uuid4()), role="user", account_type="internal", department="HR"),
            doc.id,
        )


@pytest.mark.asyncio
async def test_file_acl_denies_external_user_for_internal_document() -> None:
    doc = document(classification="internal")
    use_case = GetDocumentFileUseCase(InMemoryDocuments([doc]), FakeStorage())

    with pytest.raises(PermissionDeniedError):
        await use_case.execute(
            CurrentUser(id=str(uuid4()), role="user", account_type="external", department="HR"),
            doc.id,
        )


@pytest.mark.asyncio
async def test_file_acl_allows_internal_user_for_internal_document() -> None:
    doc = document(classification="internal")
    use_case = GetDocumentFileUseCase(InMemoryDocuments([doc]), FakeStorage())

    result = await use_case.execute(
        CurrentUser(id=str(uuid4()), role="user", account_type="internal", department="HR"),
        doc.id,
    )

    assert result.file_type == "pdf"


@pytest.mark.asyncio
async def test_file_acl_allows_admin_top_secret_bypass() -> None:
    doc = document(classification="top_secret", allowed_user_ids=[str(uuid4())])
    use_case = GetDocumentFileUseCase(InMemoryDocuments([doc]), FakeStorage())

    result = await use_case.execute(
        CurrentUser(id=str(uuid4()), role="admin", account_type="internal", department="IT"),
        doc.id,
    )

    assert result.file_type == "pdf"


@pytest.mark.asyncio
async def test_file_acl_denies_empty_department_for_secret() -> None:
    doc = document(classification="secret", allowed_departments=[""])
    use_case = GetDocumentFileUseCase(InMemoryDocuments([doc]), FakeStorage())

    with pytest.raises(PermissionDeniedError):
        await use_case.execute(
            CurrentUser(id=str(uuid4()), role="user", account_type="internal", department=""),
            doc.id,
        )


@pytest.mark.asyncio
async def test_file_acl_denies_external_user_for_secret_document() -> None:
    doc = document(classification="secret", allowed_departments=["HR"])
    use_case = GetDocumentFileUseCase(InMemoryDocuments([doc]), FakeStorage())

    with pytest.raises(PermissionDeniedError):
        await use_case.execute(
            CurrentUser(id=str(uuid4()), role="user", account_type="external", department="HR"),
            doc.id,
        )


@pytest.mark.asyncio
async def test_file_acl_allows_matching_top_secret_user() -> None:
    user_id = str(uuid4())
    doc = document(classification="top_secret", allowed_user_ids=[user_id])
    use_case = GetDocumentFileUseCase(InMemoryDocuments([doc]), FakeStorage())

    result = await use_case.execute(
        CurrentUser(id=user_id, role="user", account_type="external", department=""),
        doc.id,
    )

    assert result.file_type == "pdf"


@pytest.mark.asyncio
async def test_file_acl_denies_non_matching_top_secret_user() -> None:
    doc = document(classification="top_secret", allowed_user_ids=[str(uuid4())])
    use_case = GetDocumentFileUseCase(InMemoryDocuments([doc]), FakeStorage())

    with pytest.raises(PermissionDeniedError):
        await use_case.execute(
            CurrentUser(id=str(uuid4()), role="user", account_type="internal", department="HR"),
            doc.id,
        )


@pytest.mark.asyncio
async def test_get_document_allows_authorized_user_metadata() -> None:
    doc = document(classification="secret", allowed_departments=["Finance"])
    use_case = GetDocumentUseCase(InMemoryDocuments([doc]))

    result = await use_case.execute(
        CurrentUser(id=str(uuid4()), role="user", account_type="internal", department="Finance"),
        doc.id,
    )

    assert result.id == doc.id


@pytest.mark.asyncio
async def test_get_document_denies_unauthorized_user_metadata() -> None:
    doc = document(classification="secret", allowed_departments=["HR"])
    use_case = GetDocumentUseCase(InMemoryDocuments([doc]))

    with pytest.raises(PermissionDeniedError):
        await use_case.execute(
            CurrentUser(id=str(uuid4()), role="user", account_type="internal", department="Finance"),
            doc.id,
        )


@pytest.mark.asyncio
async def test_delete_soft_deletes_before_best_effort_storage_delete() -> None:
    events: list[str] = []
    doc = document()
    publisher = OrderedPublisher(events)
    audit = OrderedAudit(events)
    use_case = DeleteDocumentUseCase(
        OrderedDocuments([doc], events),
        FailingDeleteStorage(events),
        publisher,
        audit,
    )

    result = await use_case.execute(admin(), doc.id)

    assert result.message == "Document deleted"
    assert events == ["repo.delete", "publisher.access", "audit.log", "storage.delete"]
    assert publisher.access_payloads[0] == {
        "doc_id": doc.id,
        "classification": "internal",
        "allowed_departments": [],
        "allowed_user_ids": [],
        "deleted": True,
    }


def test_settings_rejects_weak_secret_and_non_hs256_algorithm() -> None:
    from app.core.config import Settings

    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(jwt_secret_key="change-me-in-env")
    with pytest.raises(ValueError, match="JWT_ALGORITHM"):
        Settings(jwt_secret_key="strong-test-secret", jwt_algorithm="none")


@pytest.mark.asyncio
async def test_document_auth_rejects_expired_token() -> None:
    from datetime import timedelta

    from fastapi import HTTPException
    from jose import jwt

    from app.core.config import Settings
    from app.interfaces.api.dependencies import get_current_user

    settings = Settings(jwt_secret_key="strong-test-secret")
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "role": "user",
            "account_type": "internal",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        settings.jwt_secret_key,
        algorithm="HS256",
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(token=token, settings=settings)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_document_auth_decodes_account_type() -> None:
    from datetime import timedelta

    from jose import jwt

    from app.core.config import Settings
    from app.interfaces.api.dependencies import get_current_user

    settings = Settings(jwt_secret_key="strong-test-secret")
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "role": "user",
            "account_type": "external",
            "department": "Partner",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        settings.jwt_secret_key,
        algorithm="HS256",
    )

    user = await get_current_user(token=token, settings=settings)

    assert user.account_type == "external"
    assert user.department == "Partner"


@pytest.mark.asyncio
async def test_document_auth_rejects_token_without_account_type() -> None:
    from datetime import timedelta

    from fastapi import HTTPException
    from jose import jwt

    from app.core.config import Settings
    from app.interfaces.api.dependencies import get_current_user

    settings = Settings(jwt_secret_key="strong-test-secret")
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "role": "user",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        settings.jwt_secret_key,
        algorithm="HS256",
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(token=token, settings=settings)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_nats_publisher_reuses_connection_and_drains(monkeypatch) -> None:
    from app.core.config import Settings
    from app.infrastructure.messaging import nats_publisher
    from app.infrastructure.messaging.nats_publisher import NatsPublisher

    class FakeConnection:
        def __init__(self) -> None:
            self.is_connected = True
            self.published: list[tuple[str, bytes]] = []
            self.drained = False

        async def publish(self, subject: str, data: bytes) -> None:
            self.published.append((subject, data))

        async def flush(self) -> None:
            return None

        async def drain(self) -> None:
            self.drained = True
            self.is_connected = False

    class FakeNats:
        def __init__(self) -> None:
            self.connection = FakeConnection()
            self.connect_count = 0

        async def connect(self, url: str) -> FakeConnection:
            self.connect_count += 1
            return self.connection

    fake_nats = FakeNats()
    monkeypatch.setattr(nats_publisher, "_import_nats", lambda: fake_nats)
    publisher = NatsPublisher(
        Settings(jwt_secret_key="strong-test-secret", nats_jetstream_enabled=False),
    )

    await publisher.publish_doc_access({"doc_id": "doc-1"})
    await publisher.publish_doc_access({"doc_id": "doc-2"})
    await publisher.close()

    assert fake_nats.connect_count == 1
    assert len(fake_nats.connection.published) == 2
    first_subject, first_data = fake_nats.connection.published[0]
    first_payload = json.loads(first_data.decode("utf-8"))
    assert first_subject == "doc.access"
    assert first_payload["doc_id"] == "doc-1"
    assert first_payload["event_id"]
    assert first_payload["event_version"] == 1
    assert first_payload["occurred_at"].endswith("Z")
    assert fake_nats.connection.drained is True

