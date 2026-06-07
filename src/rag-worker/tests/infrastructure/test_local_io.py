from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import types
import zipfile

import pytest

from app.infrastructure.external.local_artifact_store import LocalArtifactStore
from app.infrastructure.external.local_parser import LocalFileParser


def test_local_file_parser_reads_relative_source_under_source_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        source_root = tmp_path / "sources"
        source_root.mkdir()
        source_path = source_root / "guide.md"
        source_path.write_text("# Guide\nBody", encoding="utf-8")
        monkeypatch.setenv("SOURCE_ROOT", str(source_root))
        parser = LocalFileParser(max_workers=1)

        try:
            parsed = await parser.parse(
                document_id="doc-1",
                file_type="md",
                source_uri="local://guide.md",
            )
        finally:
            parser.close()

        assert parsed.markdown == "# Guide\nBody"
        assert parsed.source_uri == f"file://{source_path.resolve()}"

    asyncio.run(scenario())


def test_local_file_parser_rejects_path_traversal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        source_root = tmp_path / "sources"
        source_root.mkdir()
        outside = tmp_path / "outside.md"
        outside.write_text("secret", encoding="utf-8")
        monkeypatch.setenv("SOURCE_ROOT", str(source_root))
        parser = LocalFileParser(max_workers=1)

        try:
            with pytest.raises(ValueError, match="outside SOURCE_ROOT"):
                await parser.parse(
                    document_id="doc-1",
                    file_type="md",
                    source_uri=f"file://{outside.resolve()}",
                )
        finally:
            parser.close()

    asyncio.run(scenario())


def test_local_file_parser_reads_html_source_under_source_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        source_root = tmp_path / "sources"
        source_root.mkdir()
        source_path = source_root / "guide.html"
        source_path.write_text(
            "<html><body><h1>Guide</h1><p>Hello <b>world</b>.</p></body></html>",
            encoding="utf-8",
        )
        monkeypatch.setenv("SOURCE_ROOT", str(source_root))
        parser = LocalFileParser(max_workers=1)

        try:
            parsed = await parser.parse(
                document_id="doc-1",
                file_type="html",
                source_uri="local://guide.html",
            )
        finally:
            parser.close()

        assert parsed.markdown == "Guide\n\nHello world."

    asyncio.run(scenario())


def test_local_file_parser_reads_docx_source_under_source_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        source_root = tmp_path / "sources"
        source_root.mkdir()
        source_path = source_root / "guide.docx"
        with zipfile.ZipFile(source_path, "w") as archive:
            archive.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0" encoding="UTF-8"?><Types '
                'xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>',
            )
            archive.writestr(
                "word/document.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body>"
                "<w:p><w:r><w:t>Guide</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>Hello docx</w:t></w:r></w:p>"
                "</w:body>"
                "</w:document>",
            )
        monkeypatch.setenv("SOURCE_ROOT", str(source_root))
        parser = LocalFileParser(max_workers=1)

        try:
            parsed = await parser.parse(
                document_id="doc-1",
                file_type="docx",
                source_uri="local://guide.docx",
            )
        finally:
            parser.close()

        assert parsed.markdown == "Guide\n\nHello docx"

    asyncio.run(scenario())


def test_local_file_parser_reads_pptx_source_via_markitdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeMarkItDown:
        def convert(self, path: str):
            return types.SimpleNamespace(text_content=f"Converted {Path(path).name}")

    async def scenario() -> None:
        source_root = tmp_path / "sources"
        source_root.mkdir()
        source_path = source_root / "deck.pptx"
        source_path.write_bytes(b"fake-pptx")
        monkeypatch.setenv("SOURCE_ROOT", str(source_root))
        monkeypatch.setitem(
            sys.modules,
            "markitdown",
            types.SimpleNamespace(MarkItDown=FakeMarkItDown),
        )
        parser = LocalFileParser(max_workers=1)

        try:
            parsed = await parser.parse(
                document_id="doc-1",
                file_type="pptx",
                source_uri="local://deck.pptx",
            )
        finally:
            parser.close()

        assert parsed.markdown == "Converted deck.pptx"

    asyncio.run(scenario())


def test_local_file_parser_requires_extractor_for_images(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ảnh cần OCR nhưng parser không có extractor ⇒ fail-closed, không trả rỗng."""

    async def scenario() -> None:
        source_root = tmp_path / "sources"
        source_root.mkdir()
        source_path = source_root / "scan.png"
        source_path.write_bytes(b"fake-png-bytes")
        monkeypatch.setenv("SOURCE_ROOT", str(source_root))
        parser = LocalFileParser(max_workers=1, image_text_extractor=None)

        try:
            with pytest.raises(RuntimeError, match="requires OCR"):
                await parser.parse(
                    document_id="doc-1",
                    file_type="png",
                    source_uri="local://scan.png",
                )
        finally:
            parser.close()

    asyncio.run(scenario())


def test_local_file_parser_routes_image_through_ai_gateway_extractor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ảnh → VisionImage (base64+mime) → extractor (AI gateway) → markdown."""

    captured: dict = {}

    class FakeExtractor:
        async def extract(self, images):
            # Snapshot tại thời điểm gọi: parser chủ động clear page.images sau OCR
            # (G7-12 giải phóng RAM) nên không giữ reference sống để assert.
            captured["images"] = list(images)
            return "# Scanned\nrecognized text"

    async def scenario() -> None:
        source_root = tmp_path / "sources"
        source_root.mkdir()
        source_path = source_root / "scan.png"
        source_path.write_bytes(b"fake-png-bytes")
        monkeypatch.setenv("SOURCE_ROOT", str(source_root))
        parser = LocalFileParser(max_workers=1, image_text_extractor=FakeExtractor())

        try:
            parsed = await parser.parse(
                document_id="doc-1",
                file_type="png",
                source_uri="local://scan.png",
            )
        finally:
            parser.close()

        assert parsed.markdown == "# Scanned\nrecognized text"
        assert len(captured["images"]) == 1
        assert captured["images"][0].mime_type == "image/png"
        # Adapter chỉ encode base64, KHÔNG tự gọi model AI.
        assert captured["images"][0].base64_data

    asyncio.run(scenario())


def test_local_file_parser_pdf_merges_text_layer_and_embedded_image_ocr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PDF có text + ảnh nhúng: giữ text-layer, vision riêng ảnh, rồi merge."""

    fitz = pytest.importorskip("fitz")

    class FakeExtractor:
        def __init__(self) -> None:
            self.calls = 0

        async def extract(self, images):
            self.calls += 1
            return "OCR-OF-EMBEDDED-IMAGE"

    async def scenario() -> None:
        source_root = tmp_path / "sources"
        source_root.mkdir()
        pdf_path = source_root / "mixed.pdf"

        doc = fitz.open()
        page_text_only = doc.new_page()
        page_text_only.insert_text((72, 72), "Page one plain text")
        page_mixed = doc.new_page()
        page_mixed.insert_text((72, 72), "Page two text with a figure")
        png = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 120, 120)).tobytes("png")
        page_mixed.insert_image(fitz.Rect(72, 120, 300, 300), stream=png)
        doc.save(str(pdf_path))
        doc.close()

        monkeypatch.setenv("SOURCE_ROOT", str(source_root))
        extractor = FakeExtractor()
        parser = LocalFileParser(max_workers=1, image_text_extractor=extractor)
        try:
            parsed = await parser.parse(
                document_id="doc-1",
                file_type="pdf",
                source_uri="local://mixed.pdf",
            )
        finally:
            parser.close()

        # Text-layer của cả hai trang được giữ; ảnh nhúng đi qua vision và merge.
        assert "Page one plain text" in parsed.markdown
        assert "Page two text with a figure" in parsed.markdown
        assert "OCR-OF-EMBEDDED-IMAGE" in parsed.markdown
        # Trang chỉ-text KHÔNG gọi vision; chỉ trang có ảnh mới gọi (1 lần).
        assert extractor.calls == 1

    asyncio.run(scenario())


def test_local_artifact_store_rejects_reads_outside_artifact_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        artifact_root = tmp_path / "artifacts"
        artifact_root.mkdir()
        outside = tmp_path / "outside.md"
        outside.write_text("secret", encoding="utf-8")
        monkeypatch.setenv("ARTIFACT_ROOT", str(artifact_root))

        with pytest.raises(ValueError, match="outside ARTIFACT_ROOT"):
            await LocalArtifactStore().read_markdown(f"artifact://{outside.resolve()}")

    asyncio.run(scenario())


def test_local_artifact_store_default_root_uses_rag_worker_service_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        monkeypatch.delenv("ARTIFACT_ROOT", raising=False)
        monkeypatch.chdir(tmp_path)

        artifact_uri = await LocalArtifactStore().write_markdown("doc-1", "# Hello")

        assert "src/rag-worker/.artifacts" in artifact_uri.replace("\\", "/")
        assert Path(artifact_uri[len("artifact://") :]).is_file()

    asyncio.run(scenario())


def test_local_file_parser_pdf_reader_selectable_via_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """readers config chọn engine giải mã PDF (pypdf) thay mặc định (pymupdf),
    KHÔNG sửa code. pypdf là text-only nên dùng fake module để kiểm định tuyến."""

    class _FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class FakePdfReader:
        def __init__(self, path: str) -> None:
            self.pages = [_FakePage("Hello from pypdf"), _FakePage("page two")]

    async def scenario() -> None:
        source_root = tmp_path / "sources"
        source_root.mkdir()
        (source_root / "doc.pdf").write_bytes(b"%PDF-fake")
        monkeypatch.setenv("SOURCE_ROOT", str(source_root))
        monkeypatch.setitem(
            sys.modules, "pypdf", types.SimpleNamespace(PdfReader=FakePdfReader)
        )
        parser = LocalFileParser(
            max_workers=1,
            readers_config={"pdf": {"impl": "pypdf"}},
        )
        try:
            parsed = await parser.parse(
                document_id="doc-1", file_type="pdf", source_uri="local://doc.pdf"
            )
        finally:
            parser.close()

        assert "Hello from pypdf" in parsed.markdown
        assert "page two" in parsed.markdown

    asyncio.run(scenario())


def test_local_file_parser_unknown_reader_impl_raises(tmp_path: Path) -> None:
    parser = LocalFileParser(readers_config={"pdf": {"impl": "does_not_exist"}})
    try:
        with pytest.raises(ValueError, match="chua dang ky"):
            parser._reader_for_suffix("pdf")
    finally:
        parser.close()
