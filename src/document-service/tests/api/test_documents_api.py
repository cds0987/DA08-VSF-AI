import os
from datetime import datetime, timezone
from uuid import uuid4

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
) -> Document:
    return Document(
        id=document_id,
        name="policy.pdf",
        file_type="pdf",
        gcs_key=f"raw/{document_id}/policy.pdf",
        status=DocumentStatus.QUEUED,
        uploaded_by=ADMIN_ID,
        created_at=datetime.now(timezone.utc),
        classification=classification,
        allowed_departments=allowed_departments or [],
        allowed_user_ids=allowed_user_ids or [],
    )


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

