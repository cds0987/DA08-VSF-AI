from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.application.auth import CurrentUser
from app.application.exceptions import PermissionDeniedError, ValidationError
from app.application.use_cases.documents.common import MAX_FILE_BYTES
from app.application.use_cases.documents.get_document_file_use_case import GetDocumentFileUseCase
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


class FakePublisher:
    def __init__(self) -> None:
        self.ingest_payloads: list[dict] = []
        self.access_payloads: list[dict] = []

    async def publish_doc_ingest(self, payload: dict) -> None:
        self.ingest_payloads.append(payload)

    async def publish_doc_access(self, payload: dict) -> None:
        self.access_payloads.append(payload)


class FakeAudit:
    def __init__(self) -> None:
        self.actions: list[str] = []

    async def log(self, action: str, **kwargs: object) -> None:
        self.actions.append(action)


def admin() -> CurrentUser:
    return CurrentUser(id=str(uuid4()), role="admin", department="IT")


def document(
    classification: str = "internal",
    allowed_departments: list[str] | None = None,
    allowed_user_ids: list[str] | None = None,
) -> Document:
    return Document(
        id=str(uuid4()),
        name="policy.pdf",
        file_type="pdf",
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


def test_nats_event_metadata_is_added_to_doc_events() -> None:
    payload = _with_event_metadata("doc.ingest", {"doc_id": "doc-1"})

    assert payload["doc_id"] == "doc-1"
    assert payload["event_version"] == 1
    assert payload["event_id"]
    assert payload["occurred_at"].endswith("Z")


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
    assert publisher.ingest_payloads[0]["doc_id"] == result.document_id
    assert publisher.ingest_payloads[0]["gcs_key"].startswith(
        f"gs://rag-chatbot-docs/raw/{result.document_id}/"
    )
    assert publisher.ingest_payloads[0]["document_name"] == "policy.pdf"
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
async def test_file_acl_allows_matching_secret_department() -> None:
    doc = document(classification="secret", allowed_departments=["HR"])
    use_case = GetDocumentFileUseCase(InMemoryDocuments([doc]), FakeStorage())

    result = await use_case.execute(CurrentUser(id=str(uuid4()), role="user", department="HR"), doc.id)

    assert result.file_type == "pdf"
    assert result.expires_in == 300


@pytest.mark.asyncio
async def test_file_acl_denies_non_matching_top_secret_user() -> None:
    doc = document(classification="top_secret", allowed_user_ids=[str(uuid4())])
    use_case = GetDocumentFileUseCase(InMemoryDocuments([doc]), FakeStorage())

    with pytest.raises(PermissionDeniedError):
        await use_case.execute(CurrentUser(id=str(uuid4()), role="admin", department="IT"), doc.id)

