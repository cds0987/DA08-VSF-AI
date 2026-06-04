from __future__ import annotations

import asyncio
from pathlib import Path
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


def test_local_file_parser_requires_ocr_command_for_images(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        source_root = tmp_path / "sources"
        source_root.mkdir()
        source_path = source_root / "scan.png"
        source_path.write_bytes(b"not-a-real-image")
        monkeypatch.setenv("SOURCE_ROOT", str(source_root))
        monkeypatch.setenv("OCR_COMMAND", "definitely-missing-ocr")
        parser = LocalFileParser(max_workers=1)

        try:
            with pytest.raises(RuntimeError, match="OCR command"):
                await parser.parse(
                    document_id="doc-1",
                    file_type="png",
                    source_uri="local://scan.png",
                )
        finally:
            parser.close()

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
