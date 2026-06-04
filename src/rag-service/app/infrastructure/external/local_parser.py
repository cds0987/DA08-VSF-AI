from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

from app.domain.repositories.parser import ParsedArtifact, Parser


def _allowed_source_root() -> Path:
    raw = os.getenv("SOURCE_ROOT", os.getcwd())
    return Path(raw).resolve()


def _max_source_size_bytes() -> int:
    return int(os.getenv("MAX_SOURCE_SIZE_BYTES", str(10 * 1024 * 1024)))


def _max_ocr_pages() -> int:
    return int(os.getenv("MAX_OCR_PAGES", "25"))


def _ocr_language() -> str:
    return os.getenv("OCR_LANGUAGE", "eng").strip() or "eng"


def _ocr_command() -> str:
    return os.getenv("OCR_COMMAND", "tesseract").strip() or "tesseract"


def _pdf_ocr_scale() -> float:
    return float(os.getenv("PDF_OCR_SCALE", "2.0"))


def _resolve_local_source(source_uri: str) -> Path:
    if source_uri.startswith("file://"):
        candidate = Path(source_uri[len("file://") :])
    elif source_uri.startswith("local://"):
        candidate = _allowed_source_root() / source_uri[len("local://") :]
    else:
        raw = Path(source_uri)
        candidate = raw if raw.is_absolute() else _allowed_source_root() / raw
    resolved = candidate.resolve()
    root = _allowed_source_root()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"source path outside SOURCE_ROOT: {resolved}") from exc
    return resolved


def _ensure_source_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"source file not found: {path}")
    size = path.stat().st_size
    if size > _max_source_size_bytes():
        raise ValueError(f"source too large: {size} bytes > MAX_SOURCE_SIZE_BYTES")


def _normalize_markdown(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    collapsed: list[str] = []
    previous_blank = False
    for line in lines:
        blank = not line.strip()
        if blank:
            if previous_blank:
                continue
            collapsed.append("")
            previous_blank = True
            continue
        collapsed.append(line)
        previous_blank = False
    return "\n".join(collapsed).strip()


def _read_text_file(path: Path) -> str:
    _ensure_source_file(path)
    return path.read_text(encoding="utf-8")


class _HTMLToText(HTMLParser):
    _BLOCK_TAGS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "div",
        "dl",
        "dt",
        "dd",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if data:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def _read_html_file(path: Path) -> str:
    _ensure_source_file(path)
    parser = _HTMLToText()
    parser.feed(path.read_text(encoding="utf-8"))
    parser.close()
    return parser.text()


def _read_docx_file(path: Path) -> str:
    _ensure_source_file(path)
    with zipfile.ZipFile(path) as archive:
        try:
            document_xml = archive.read("word/document.xml")
        except KeyError as exc:
            raise ValueError(f"invalid docx file: {path}") from exc
    root = ElementTree.fromstring(document_xml)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", ns):
        parts: list[str] = []
        for node in paragraph.iter():
            tag = node.tag.rsplit("}", 1)[-1]
            if tag == "t" and node.text:
                parts.append(node.text)
            elif tag == "tab":
                parts.append("\t")
            elif tag == "br":
                parts.append("\n")
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def _run_tesseract(path: Path) -> str:
    command = _ocr_command()
    resolved = shutil.which(command)
    if resolved is None:
        raise RuntimeError(
            f"OCR command {command!r} is not available; install Tesseract or set OCR_COMMAND"
        )
    result = subprocess.run(
        [resolved, str(path), "stdout", "-l", _ocr_language()],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip() or "unknown OCR failure"
        raise RuntimeError(f"OCR failed for {path.name}: {stderr}")
    text = _normalize_markdown(result.stdout)
    if not text:
        raise ValueError(f"OCR produced empty text for source: {path}")
    return text


def _ocr_image_file(path: Path) -> str:
    _ensure_source_file(path)
    return _run_tesseract(path)


def _read_pdf_file(path: Path) -> str:
    _ensure_source_file(path)
    try:
        import fitz
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("PyMuPDF is required to parse PDF sources") from exc
    with fitz.open(path) as doc:
        text_layer = _normalize_markdown(
            "\n".join(page.get_text("text") for page in doc)
        )
        if text_layer:
            return text_layer
        if len(doc) > _max_ocr_pages():
            raise ValueError(
                f"scanned PDF requires OCR but exceeds MAX_OCR_PAGES ({len(doc)} > {_max_ocr_pages()})"
            )
        scale = _pdf_ocr_scale()
        with tempfile.TemporaryDirectory(prefix="rag-pdf-ocr-") as tmpdir:
            page_texts: list[str] = []
            for page_number, page in enumerate(doc, start=1):
                image_path = Path(tmpdir) / f"page-{page_number}.png"
                pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                pixmap.save(str(image_path))
                page_texts.append(_run_tesseract(image_path))
        ocr_text = _normalize_markdown("\n\n".join(page_texts))
        if not ocr_text:
            raise ValueError(f"OCR produced empty text for scanned PDF: {path}")
        return ocr_text


def _convert_with_markitdown(path: Path) -> str:
    try:
        from markitdown import MarkItDown
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("MarkItDown is not installed") from exc
    return MarkItDown().convert(str(path)).text_content


class LocalFileParser(Parser):
    def __init__(self, *, max_workers: int = 2):
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="rag-parse",
        )

    async def parse(
        self,
        *,
        document_id: str,
        file_type: str,
        source_uri: str,
    ) -> ParsedArtifact:
        del document_id
        path = _resolve_local_source(source_uri)
        suffix = file_type.lower().strip(".")
        reader = self._reader_for_suffix(suffix)
        loop = asyncio.get_running_loop()
        markdown = await loop.run_in_executor(self._executor, reader, path)
        return ParsedArtifact(
            markdown=_normalize_markdown(markdown),
            source_uri=f"file://{path}",
        )

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _reader_for_suffix(self, suffix: str):
        if suffix in {"md", "txt"}:
            return _read_text_file
        if suffix in {"html", "htm"}:
            return _read_html_file
        if suffix == "docx":
            return _read_docx_file
        if suffix == "pdf":
            return _read_pdf_file
        if suffix in {"png", "jpg", "jpeg", "tif", "tiff", "bmp", "gif", "webp"}:
            return _ocr_image_file
        if suffix in {"doc", "ppt", "pptx", "xls", "xlsx"}:
            return _convert_with_markitdown
        raise ValueError(f"unsupported file_type for local parser: {suffix}")
