import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET_KEY", "test-document-service-secret")

from app.application.auth import CurrentUser
from app.application.use_cases.documents.delete_document_use_case import DeleteDocumentUseCase
from app.application.use_cases.documents.get_document_file_use_case import GetDocumentFileUseCase
from app.application.use_cases.documents.get_document_use_case import GetDocumentUseCase
from app.application.use_cases.documents.list_documents_use_case import ListDocumentsUseCase
from app.application.use_cases.documents.upload_document_use_case import UploadDocumentUseCase
from app.domain.entities.document import Document, DocumentStatus
from app.interfaces.api import dependencies
from app.interfaces.api.main import app
from tests.unit.test_document_use_cases import FakeAudit, FakePublisher, FakeStorage, InMemoryDocuments


ADMIN_ID = str(uuid4())
DOC_ID = str(uuid4())


def admin_user() -> CurrentUser:
    return CurrentUser(id=ADMIN_ID, role="admin", account_type="internal", department="IT")


def normal_user() -> CurrentUser:
    return CurrentUser(id=str(uuid4()), role="user", account_type="internal", department="Finance")


def external_user() -> CurrentUser:
    return CurrentUser(id=str(uuid4()), role="user", account_type="external", department="Finance")


def sample_document(
    document_id: str = DOC_ID,
    classification: str = "internal",
    allowed_departments: list[str] | None = None,
    allowed_user_ids: list[str] | None = None,
    file_type: str = "pdf",
) -> Document:
    normalized_file_type = file_type.lstrip(".").lower()
    return Document(
        id=document_id,
        name=f"policy.{normalized_file_type}",
        file_type=file_type,
        gcs_key=f"raw/{document_id}/policy.{normalized_file_type}",
        status=DocumentStatus.QUEUED,
        uploaded_by=ADMIN_ID,
        created_at=datetime.now(timezone.utc),
        classification=classification,
        allowed_departments=allowed_departments or [],
        allowed_user_ids=allowed_user_ids or [],
    )


class InvalidUrlStorage(FakeStorage):
    async def generate_presigned_url(self, key: str, expires_in: int = 300) -> str:
        return ""


def setup_function() -> None:
    app.dependency_overrides.clear()


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_upload_requires_admin() -> None:
    app.dependency_overrides[dependencies.get_current_user] = normal_user

    response = TestClient(app).post(
        "/documents/upload",
        data={"classification": "internal"},
        files={"file": ("policy.pdf", b"content", "application/pdf")},
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin only"


def test_admin_upload_returns_queued_and_publishes_events() -> None:
    repo = InMemoryDocuments()
    publisher = FakePublisher()
    use_case = UploadDocumentUseCase(repo, FakeStorage(), publisher, FakeAudit())
    app.dependency_overrides[dependencies.get_current_user] = admin_user
    app.dependency_overrides[dependencies.get_upload_document_use_case] = lambda: use_case

    response = TestClient(app).post(
        "/documents/upload",
        data={"classification": "secret", "allowed_departments": "HR"},
        files={"file": ("policy.pdf", b"content", "application/pdf")},
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["message"] == "Ingestion started"
    assert publisher.ingest_payloads[0]["doc_id"] == body["document_id"]
    assert publisher.ingest_payloads[0]["gcs_key"].startswith(
        f"gs://rag-chatbot-docs/raw/{body['document_id']}/"
    )
    assert publisher.ingest_payloads[0]["document_name"] == "policy.pdf"
    assert "s3_key" not in publisher.ingest_payloads[0]
    assert publisher.access_payloads[0]["deleted"] is False


def test_admin_can_list_get_and_delete_documents() -> None:
    repo = InMemoryDocuments([sample_document()])
    publisher = FakePublisher()
    app.dependency_overrides[dependencies.get_current_user] = admin_user
    app.dependency_overrides[dependencies.get_list_documents_use_case] = (
        lambda: ListDocumentsUseCase(repo)
    )
    app.dependency_overrides[dependencies.get_get_document_use_case] = (
        lambda: GetDocumentUseCase(repo)
    )
    app.dependency_overrides[dependencies.get_delete_document_use_case] = (
        lambda: DeleteDocumentUseCase(repo, FakeStorage(), publisher, FakeAudit())
    )

    client = TestClient(app)
    list_response = client.get("/documents?status=queued")
    get_response = client.get(f"/documents/{DOC_ID}")
    delete_response = client.delete(f"/documents/{DOC_ID}")

    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert get_response.status_code == 200
    assert get_response.json()["id"] == DOC_ID
    assert delete_response.status_code == 200
    assert delete_response.json() == {"message": "Document deleted"}
    assert publisher.access_payloads[0]["deleted"] is True


def test_admin_bulk_delete_removes_many() -> None:
    from app.application.use_cases.documents.bulk_delete_documents_use_case import (
        BulkDeleteDocumentsUseCase,
    )

    docs = [sample_document(document_id=str(uuid4())) for _ in range(3)]
    repo = InMemoryDocuments(docs)
    publisher = FakePublisher()
    delete_uc = DeleteDocumentUseCase(repo, FakeStorage(), publisher, FakeAudit())
    app.dependency_overrides[dependencies.get_current_user] = admin_user
    app.dependency_overrides[dependencies.get_bulk_delete_documents_use_case] = (
        lambda: BulkDeleteDocumentsUseCase(delete_uc)
    )

    response = TestClient(app).post(
        "/documents/bulk-delete",
        json={"document_ids": [d.id for d in docs] + ["missing-id"]},
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["deleted"] == 3
    assert body["not_found"] == ["missing-id"]
    assert body["failed"] == []
    assert len(publisher.access_payloads) == 3
    assert all(p["deleted"] is True for p in publisher.access_payloads)


def test_bulk_delete_requires_admin() -> None:
    app.dependency_overrides[dependencies.get_current_user] = normal_user

    response = TestClient(app).post(
        "/documents/bulk-delete",
        json={"document_ids": [DOC_ID]},
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 403


def test_bulk_delete_rejects_empty_list() -> None:
    app.dependency_overrides[dependencies.get_current_user] = admin_user

    response = TestClient(app).post(
        "/documents/bulk-delete",
        json={"document_ids": []},
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 422


def test_authorized_user_can_get_document_detail() -> None:
    doc = sample_document(classification="secret", allowed_departments=["Finance"])
    repo = InMemoryDocuments([doc])
    app.dependency_overrides[dependencies.get_current_user] = normal_user
    app.dependency_overrides[dependencies.get_get_document_use_case] = (
        lambda: GetDocumentUseCase(repo)
    )

    response = TestClient(app).get(
        f"/documents/{doc.id}",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == doc.id


def test_unauthorized_user_cannot_get_document_detail() -> None:
    doc = sample_document(classification="secret", allowed_departments=["HR"])
    repo = InMemoryDocuments([doc])
    app.dependency_overrides[dependencies.get_current_user] = normal_user
    app.dependency_overrides[dependencies.get_get_document_use_case] = (
        lambda: GetDocumentUseCase(repo)
    )

    response = TestClient(app).get(
        f"/documents/{doc.id}",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 403


def test_invalid_token_does_not_print_raw_token(capsys) -> None:
    token = "leaky-token-value"

    response = TestClient(app).get(
        f"/documents/{DOC_ID}/file",
        headers={"Authorization": f"Bearer {token}"},
    )

    captured = capsys.readouterr()
    assert response.status_code == 401
    assert token not in captured.out
    assert token not in captured.err


def test_file_presign_forbidden_when_acl_does_not_match() -> None:
    doc = sample_document(classification="secret", allowed_departments=["HR"])
    repo = InMemoryDocuments([doc])
    app.dependency_overrides[dependencies.get_current_user] = normal_user
    app.dependency_overrides[dependencies.get_get_document_file_use_case] = (
        lambda: GetDocumentFileUseCase(repo, FakeStorage())
    )

    response = TestClient(app).get(
        f"/documents/{doc.id}/file",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 403


def test_external_user_cannot_get_internal_document_file() -> None:
    doc = sample_document(classification="internal")
    repo = InMemoryDocuments([doc])
    app.dependency_overrides[dependencies.get_current_user] = external_user
    app.dependency_overrides[dependencies.get_get_document_file_use_case] = (
        lambda: GetDocumentFileUseCase(repo, FakeStorage())
    )

    response = TestClient(app).get(
        f"/documents/{doc.id}/file",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 403


def test_internal_user_can_get_internal_document_file() -> None:
    doc = sample_document(classification="internal")
    repo = InMemoryDocuments([doc])
    app.dependency_overrides[dependencies.get_current_user] = normal_user
    app.dependency_overrides[dependencies.get_get_document_file_use_case] = (
        lambda: GetDocumentFileUseCase(repo, FakeStorage())
    )

    response = TestClient(app).get(
        f"/documents/{doc.id}/file",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.json()["file_type"] == "pdf"


@pytest.mark.parametrize("file_type", ["pdf", "docx", "txt", "xlsx", "csv", "pptx", "md"])
def test_document_file_contract_for_supported_extensions(file_type: str) -> None:
    doc = sample_document(document_id=str(uuid4()), file_type=file_type)
    repo = InMemoryDocuments([doc])
    app.dependency_overrides[dependencies.get_current_user] = normal_user
    app.dependency_overrides[dependencies.get_get_document_file_use_case] = (
        lambda: GetDocumentFileUseCase(repo, FakeStorage())
    )

    response = TestClient(app).get(
        f"/documents/{doc.id}/file",
        headers={"Authorization": "Bearer token"},
    )

    body = response.json()
    assert response.status_code == 200
    assert set(body) == {"url", "file_type", "expires_in"}
    assert body["url"].startswith("https://")
    assert body["file_type"] == file_type
    assert not body["file_type"].startswith(".")
    assert body["expires_in"] == 300


def test_document_file_normalizes_legacy_file_type() -> None:
    doc = sample_document(document_id=str(uuid4()), file_type=".PDF")
    repo = InMemoryDocuments([doc])
    app.dependency_overrides[dependencies.get_current_user] = normal_user
    app.dependency_overrides[dependencies.get_get_document_file_use_case] = (
        lambda: GetDocumentFileUseCase(repo, FakeStorage())
    )

    response = TestClient(app).get(
        f"/documents/{doc.id}/file",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.json()["file_type"] == "pdf"


def test_document_file_missing_document_returns_404() -> None:
    repo = InMemoryDocuments()
    app.dependency_overrides[dependencies.get_current_user] = normal_user
    app.dependency_overrides[dependencies.get_get_document_file_use_case] = (
        lambda: GetDocumentFileUseCase(repo, FakeStorage())
    )

    response = TestClient(app).get(
        f"/documents/{uuid4()}/file",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 404


def test_document_file_invalid_file_type_returns_non_200() -> None:
    doc = sample_document(document_id=str(uuid4()), file_type="exe")
    repo = InMemoryDocuments([doc])
    app.dependency_overrides[dependencies.get_current_user] = normal_user
    app.dependency_overrides[dependencies.get_get_document_file_use_case] = (
        lambda: GetDocumentFileUseCase(repo, FakeStorage())
    )

    response = TestClient(app).get(
        f"/documents/{doc.id}/file",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 503


def test_document_file_invalid_signed_url_returns_non_200() -> None:
    doc = sample_document(document_id=str(uuid4()))
    repo = InMemoryDocuments([doc])
    app.dependency_overrides[dependencies.get_current_user] = normal_user
    app.dependency_overrides[dependencies.get_get_document_file_use_case] = (
        lambda: GetDocumentFileUseCase(repo, InvalidUrlStorage())
    )

    response = TestClient(app).get(
        f"/documents/{doc.id}/file",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 503


# --- /file/raw: proxy-stream giữ file trên domain vsfchat (KHÔNG nhảy GCS/officeapps) ---

from app.application.use_cases.documents.get_document_file_stream_use_case import (  # noqa: E402
    GetDocumentFileStreamUseCase,
)
from app.application.use_cases.documents.get_document_file_preview_use_case import (  # noqa: E402
    GetDocumentFilePreviewUseCase,
)
from app.interfaces.api.dependencies import get_get_document_file_preview_use_case  # noqa: E402
from tests.unit.test_document_file_stream_use_case import StreamStorage  # noqa: E402


def test_file_raw_streams_pdf_inline() -> None:
    doc = sample_document(document_id=str(uuid4()), file_type="pdf")
    repo = InMemoryDocuments([doc])
    storage = StreamStorage(b"%PDF-1.4 stream-body")
    app.dependency_overrides[dependencies.get_current_user] = normal_user
    app.dependency_overrides[dependencies.get_get_document_file_stream_use_case] = (
        lambda: GetDocumentFileStreamUseCase(repo, storage)
    )

    response = TestClient(app).get(
        f"/documents/{doc.id}/file/raw",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 stream-body"
    assert response.headers["content-type"] == "application/pdf"
    assert "inline" in response.headers["content-disposition"]
    assert "policy.pdf" in response.headers["content-disposition"]


def test_file_raw_office_file_is_attachment() -> None:
    doc = sample_document(document_id=str(uuid4()), file_type="docx")
    repo = InMemoryDocuments([doc])
    app.dependency_overrides[dependencies.get_current_user] = normal_user
    app.dependency_overrides[dependencies.get_get_document_file_stream_use_case] = (
        lambda: GetDocumentFileStreamUseCase(repo, StreamStorage(b"PK docx"))
    )

    response = TestClient(app).get(
        f"/documents/{doc.id}/file/raw",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]


def test_file_raw_forbidden_when_acl_does_not_match() -> None:
    doc = sample_document(classification="secret", allowed_departments=["HR"])
    repo = InMemoryDocuments([doc])
    app.dependency_overrides[dependencies.get_current_user] = normal_user
    app.dependency_overrides[dependencies.get_get_document_file_stream_use_case] = (
        lambda: GetDocumentFileStreamUseCase(repo, StreamStorage())
    )

    response = TestClient(app).get(
        f"/documents/{doc.id}/file/raw",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 403


# --- /file/preview: convert office sang PDF qua Gotenberg, cache GCS, native passthrough ---


class _PreviewStorage:
    def __init__(self) -> None:
        self._files: dict[str, bytes] = {}
        self.uploads: list[tuple[str, bytes]] = []

    def seed(self, key: str, content: bytes) -> None:
        self._files[key] = content

    async def file_exists(self, key: str) -> bool:
        return key in self._files

    async def download_file(self, key: str) -> bytes:
        if key not in self._files:
            raise RuntimeError("not found")
        return self._files[key]

    async def upload_file(self, key: str, content: bytes, content_type: str | None = None) -> None:
        self.uploads.append((key, content))
        self._files[key] = content


class _OkConverter:
    async def convert_to_pdf(self, content: bytes, filename: str) -> bytes:
        return b"%PDF-1.7 converted"


class _BadConverter:
    async def convert_to_pdf(self, content: bytes, filename: str) -> bytes:
        from app.application.exceptions import ConversionError
        raise ConversionError("boom")


def test_file_preview_streams_pdf_inline() -> None:
    doc = sample_document(document_id=str(uuid4()), file_type="pdf")
    repo = InMemoryDocuments([doc])
    storage = _PreviewStorage()
    storage.seed(doc.gcs_key, b"%PDF-1.4 native")
    app.dependency_overrides[dependencies.get_current_user] = normal_user
    app.dependency_overrides[get_get_document_file_preview_use_case] = lambda: (
        GetDocumentFilePreviewUseCase(repo, storage, _OkConverter())
    )

    response = TestClient(app).get(
        f"/documents/{doc.id}/file/preview",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert "inline" in response.headers["content-disposition"]
    assert response.content == b"%PDF-1.4 native"


def test_file_preview_converts_office_to_pdf() -> None:
    doc = sample_document(document_id=str(uuid4()), file_type="docx")
    repo = InMemoryDocuments([doc])
    storage = _PreviewStorage()
    storage.seed(doc.gcs_key, b"docx-bytes")
    app.dependency_overrides[dependencies.get_current_user] = normal_user
    app.dependency_overrides[get_get_document_file_preview_use_case] = lambda: (
        GetDocumentFilePreviewUseCase(repo, storage, _OkConverter())
    )

    response = TestClient(app).get(
        f"/documents/{doc.id}/file/preview",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.content == b"%PDF-1.7 converted"
    assert storage.uploads == [(f"previews/{doc.id}.pdf", b"%PDF-1.7 converted")]


def test_file_preview_returns_503_on_convert_error() -> None:
    doc = sample_document(document_id=str(uuid4()), file_type="docx")
    repo = InMemoryDocuments([doc])
    storage = _PreviewStorage()
    storage.seed(doc.gcs_key, b"docx-bytes")
    app.dependency_overrides[dependencies.get_current_user] = normal_user
    app.dependency_overrides[get_get_document_file_preview_use_case] = lambda: (
        GetDocumentFilePreviewUseCase(repo, storage, _BadConverter())
    )

    response = TestClient(app).get(
        f"/documents/{doc.id}/file/preview",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 503

