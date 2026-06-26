from uuid import uuid4

import pytest

from app.application.exceptions import (
    ConversionError,
    NotFoundError,
    PermissionDeniedError,
    StorageError,
)
from app.application.use_cases.documents.get_document_file_preview_use_case import (
    GetDocumentFilePreviewUseCase,
)
from tests.unit.test_document_use_cases import InMemoryDocuments, document


class FakePreviewStorage:
    """Fake storage: bytes theo key + ghi nhận upload + cờ tồn tại preview."""

    def __init__(self, original: bytes = b"docx-bytes") -> None:
        self._files: dict[str, bytes] = {}
        self._original = original
        self.uploads: list[tuple[str, bytes]] = []

    def seed_original(self, key: str) -> None:
        self._files[key] = self._original

    def seed_preview(self, key: str, content: bytes) -> None:
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


class CountingConverter:
    def __init__(self, output: bytes = b"%PDF-1.7 converted") -> None:
        self.output = output
        self.calls = 0

    async def convert_to_pdf(self, content: bytes, filename: str) -> bytes:
        self.calls += 1
        return self.output


class FailingConverter:
    async def convert_to_pdf(self, content: bytes, filename: str) -> bytes:
        raise ConversionError("boom")


def viewer():
    from app.application.auth import CurrentUser
    return CurrentUser(id=str(uuid4()), role="user", account_type="internal", department="HR")


@pytest.mark.asyncio
async def test_native_pdf_passthrough_inline() -> None:
    doc = document(file_type="pdf")
    storage = FakePreviewStorage(original=b"%PDF-1.4 native")
    storage.seed_original(doc.gcs_key)
    uc = GetDocumentFilePreviewUseCase(InMemoryDocuments([doc]), storage, CountingConverter())

    result = await uc.execute(viewer(), doc.id)

    assert result.content == b"%PDF-1.4 native"
    assert result.media_type == "application/pdf"
    assert storage.uploads == []  # native KHÔNG cache


@pytest.mark.asyncio
async def test_office_cache_miss_converts_and_caches() -> None:
    doc = document(file_type="docx")
    storage = FakePreviewStorage()
    storage.seed_original(doc.gcs_key)
    converter = CountingConverter()
    uc = GetDocumentFilePreviewUseCase(InMemoryDocuments([doc]), storage, converter)

    result = await uc.execute(viewer(), doc.id)

    assert result.media_type == "application/pdf"
    assert result.content == b"%PDF-1.7 converted"
    assert converter.calls == 1
    assert storage.uploads == [(f"previews/{doc.id}.pdf", b"%PDF-1.7 converted")]


@pytest.mark.asyncio
async def test_office_cache_hit_skips_convert() -> None:
    doc = document(file_type="docx")
    storage = FakePreviewStorage()
    storage.seed_original(doc.gcs_key)
    storage.seed_preview(f"previews/{doc.id}.pdf", b"%PDF-1.5 cached")
    converter = CountingConverter()
    uc = GetDocumentFilePreviewUseCase(InMemoryDocuments([doc]), storage, converter)

    result = await uc.execute(viewer(), doc.id)

    assert result.content == b"%PDF-1.5 cached"
    assert converter.calls == 0


@pytest.mark.asyncio
async def test_office_corrupt_cache_reconverts() -> None:
    doc = document(file_type="docx")
    storage = FakePreviewStorage()
    storage.seed_original(doc.gcs_key)
    storage.seed_preview(f"previews/{doc.id}.pdf", b"GARBAGE")  # không phải %PDF-
    converter = CountingConverter()
    uc = GetDocumentFilePreviewUseCase(InMemoryDocuments([doc]), storage, converter)

    result = await uc.execute(viewer(), doc.id)

    assert result.content == b"%PDF-1.7 converted"
    assert converter.calls == 1
    assert (f"previews/{doc.id}.pdf", b"%PDF-1.7 converted") in storage.uploads


@pytest.mark.asyncio
async def test_office_convert_error_raises_storage_error_and_no_cache() -> None:
    doc = document(file_type="docx")
    storage = FakePreviewStorage()
    storage.seed_original(doc.gcs_key)
    uc = GetDocumentFilePreviewUseCase(InMemoryDocuments([doc]), storage, FailingConverter())

    with pytest.raises(StorageError):
        await uc.execute(viewer(), doc.id)
    assert storage.uploads == []


@pytest.mark.asyncio
async def test_missing_document_raises_not_found() -> None:
    uc = GetDocumentFilePreviewUseCase(InMemoryDocuments([]), FakePreviewStorage(), CountingConverter())
    with pytest.raises(NotFoundError):
        await uc.execute(viewer(), str(uuid4()))


@pytest.mark.asyncio
async def test_office_cache_write_failure_still_returns_pdf() -> None:
    """Cache-write failure (upload_file raises) must NOT break the request."""

    class FailingUploadStorage(FakePreviewStorage):
        async def upload_file(self, key: str, content: bytes, content_type: str | None = None) -> None:
            raise RuntimeError("storage write error")

    doc = document(file_type="docx")
    storage = FailingUploadStorage()
    storage.seed_original(doc.gcs_key)
    converter = CountingConverter()
    uc = GetDocumentFilePreviewUseCase(InMemoryDocuments([doc]), storage, converter)

    result = await uc.execute(viewer(), doc.id)

    assert result.content == b"%PDF-1.7 converted"
    assert result.media_type == "application/pdf"


@pytest.mark.asyncio
async def test_acl_denies_external_user_internal_doc() -> None:
    from app.application.auth import CurrentUser

    doc = document(classification="internal")
    storage = FakePreviewStorage()
    storage.seed_original(doc.gcs_key)
    uc = GetDocumentFilePreviewUseCase(InMemoryDocuments([doc]), storage, CountingConverter())

    with pytest.raises(PermissionDeniedError):
        await uc.execute(
            CurrentUser(id=str(uuid4()), role="user", account_type="external", department="HR"),
            doc.id,
        )
