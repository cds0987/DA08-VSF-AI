import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET_KEY", "test-document-service-secret")

from app.application.auth import CurrentUser
from app.application.use_cases.documents.upload_document_use_case import UploadDocumentUseCase
from app.interfaces.api import dependencies
from app.interfaces.api.main import app
from tests.unit.test_document_use_cases import FakeAudit, FakePublisher, FakeStorage, InMemoryDocuments


SUPPORTED_UPLOAD_FORMATS = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "md": "text/markdown",
}


def admin_user() -> CurrentUser:
    return CurrentUser(
        id=str(uuid4()),
        role="admin",
        account_type="internal",
        department="IT",
    )


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def test_upload_accepts_all_supported_file_formats() -> None:
    failed_formats: list[str] = []
    client = TestClient(app)

    for extension, content_type in SUPPORTED_UPLOAD_FORMATS.items():
        repo = InMemoryDocuments()
        storage = FakeStorage()
        publisher = FakePublisher()
        use_case = UploadDocumentUseCase(repo, storage, publisher, FakeAudit())
        app.dependency_overrides[dependencies.get_current_user] = admin_user
        app.dependency_overrides[dependencies.get_upload_document_use_case] = lambda: use_case

        filename = f"sample.{extension}"
        response = client.post(
            "/documents/upload",
            data={"classification": "internal"},
            files={"file": (filename, _sample_content(extension), content_type)},
            headers={"Authorization": "Bearer token"},
        )

        if response.status_code != 202:
            detail = response.json().get("detail", response.text)
            failed_formats.append(f"{extension}: HTTP {response.status_code} - {detail}")
            print(f"[FAIL] {extension}: HTTP {response.status_code} - {detail}")
            continue

        body = response.json()
        ingest_payload = publisher.ingest_payloads[0] if publisher.ingest_payloads else {}
        access_payload = publisher.access_payloads[0] if publisher.access_payloads else {}
        saved_document = repo.documents.get(body["document_id"])
        if (
            body["status"] != "queued"
            or saved_document is None
            or saved_document.file_type != extension
            or ingest_payload.get("file_type") != extension
            or ingest_payload.get("document_name") != filename
            or access_payload.get("deleted") is not False
        ):
            failed_formats.append(f"{extension}: response/event payload mismatch")
            print(f"[FAIL] {extension}: response/event payload mismatch")
            continue

        print(f"[OK] {extension}: uploaded as document_id={body['document_id']}")

    assert not failed_formats, "Formats not uploadable: " + "; ".join(failed_formats)


def _sample_content(extension: str) -> bytes:
    if extension == "csv":
        return b"name,department\nAlice,HR\n"
    if extension == "md":
        return b"# Policy\n\nSample markdown document.\n"
    if extension == "txt":
        return b"Sample plain text document.\n"
    return f"sample binary content for {extension}".encode("utf-8")
