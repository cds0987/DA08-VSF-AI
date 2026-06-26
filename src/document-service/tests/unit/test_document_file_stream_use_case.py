from uuid import uuid4

import pytest

from app.application.auth import CurrentUser
from app.application.exceptions import NotFoundError, PermissionDeniedError, StorageError
from app.application.use_cases.documents.get_document_file_stream_use_case import (
    GetDocumentFileStreamUseCase,
)
from tests.unit.test_document_use_cases import InMemoryDocuments, document


class StreamStorage:
    """Fake storage trả bytes cố định — kiểm proxy-stream lấy đúng key và nội dung."""

    def __init__(self, content: bytes = b"%PDF-1.4 fake-bytes") -> None:
        self.content = content
        self.downloads: list[str] = []

    async def download_file(self, key: str) -> bytes:
        self.downloads.append(key)
        return self.content


class FailingStreamStorage(StreamStorage):
    async def download_file(self, key: str) -> bytes:
        raise RuntimeError("storage unavailable")


def viewer() -> CurrentUser:
    return CurrentUser(id=str(uuid4()), role="user", account_type="internal", department="HR")


@pytest.mark.asyncio
async def test_stream_returns_pdf_bytes_inline() -> None:
    doc = document(file_type="pdf")
    storage = StreamStorage(b"%PDF-1.4 hello")
    use_case = GetDocumentFileStreamUseCase(InMemoryDocuments([doc]), storage)

    result = await use_case.execute(viewer(), doc.id)

    assert result.content == b"%PDF-1.4 hello"
    assert result.media_type == "application/pdf"
    assert result.disposition == "attachment"
    assert result.filename == "policy.pdf"
    assert storage.downloads == [doc.gcs_key]


@pytest.mark.asyncio
async def test_stream_office_file_is_attachment() -> None:
    doc = document(file_type="docx")
    use_case = GetDocumentFileStreamUseCase(InMemoryDocuments([doc]), StreamStorage())

    result = await use_case.execute(viewer(), doc.id)

    assert result.disposition == "attachment"
    assert result.media_type == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


@pytest.mark.asyncio
async def test_stream_normalizes_legacy_file_type() -> None:
    doc = document(file_type=".PDF")
    use_case = GetDocumentFileStreamUseCase(InMemoryDocuments([doc]), StreamStorage())

    result = await use_case.execute(viewer(), doc.id)

    assert result.media_type == "application/pdf"


@pytest.mark.asyncio
async def test_stream_rejects_unsupported_file_type() -> None:
    doc = document(file_type="exe")
    use_case = GetDocumentFileStreamUseCase(InMemoryDocuments([doc]), StreamStorage())

    with pytest.raises(StorageError):
        await use_case.execute(viewer(), doc.id)


@pytest.mark.asyncio
async def test_stream_missing_document_raises_not_found() -> None:
    use_case = GetDocumentFileStreamUseCase(InMemoryDocuments([]), StreamStorage())

    with pytest.raises(NotFoundError):
        await use_case.execute(viewer(), str(uuid4()))


@pytest.mark.asyncio
async def test_stream_denies_external_user_for_internal_document() -> None:
    doc = document(classification="internal")
    use_case = GetDocumentFileStreamUseCase(InMemoryDocuments([doc]), StreamStorage())

    with pytest.raises(PermissionDeniedError):
        await use_case.execute(
            CurrentUser(id=str(uuid4()), role="user", account_type="external", department="HR"),
            doc.id,
        )


@pytest.mark.asyncio
async def test_stream_wraps_storage_errors() -> None:
    doc = document(file_type="pdf")
    use_case = GetDocumentFileStreamUseCase(InMemoryDocuments([doc]), FailingStreamStorage())

    with pytest.raises(StorageError):
        await use_case.execute(viewer(), doc.id)


@pytest.mark.asyncio
async def test_stream_secret_resolves_live_department_from_hr() -> None:
    from tests.unit.test_document_use_cases import _FakeHrDept

    doc = document(classification="secret", allowed_departments=["HR"])
    hr = _FakeHrDept("HR")
    use_case = GetDocumentFileStreamUseCase(InMemoryDocuments([doc]), StreamStorage(), hr)

    result = await use_case.execute(
        CurrentUser(id=str(uuid4()), role="user", account_type="internal", department=""),
        doc.id,
    )

    assert result.media_type == "application/pdf"
    assert hr.calls == 1
