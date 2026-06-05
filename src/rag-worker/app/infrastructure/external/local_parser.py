from __future__ import annotations

import asyncio
import base64
import os
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

from app.domain.repositories.parser import ParsedArtifact, Parser
from core_engine.ai import VisionImage
from core_engine.ocr import ImageTextExtractor

_IMAGE_MIME_BY_SUFFIX = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "tif": "image/tiff",
    "tiff": "image/tiff",
    "bmp": "image/bmp",
    "gif": "image/gif",
    "webp": "image/webp",
}
# fitz/extract_image trả `ext` (vd "jpeg","png"); map sang MIME image hợp lệ.
_IMAGE_MIME_BY_EXT = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "tiff": "image/tiff",
    "tif": "image/tiff",
    "bmp": "image/bmp",
    "gif": "image/gif",
    "webp": "image/webp",
}


def _allowed_source_root() -> Path:
    raw = os.getenv("SOURCE_ROOT", os.getcwd())
    return Path(raw).resolve()


def _max_source_size_bytes() -> int:
    return int(os.getenv("MAX_SOURCE_SIZE_BYTES", str(10 * 1024 * 1024)))


def _max_ocr_pages() -> int:
    # Trần số ảnh gửi vision mỗi tài liệu (chặn chi phí). Giữ tên env cũ.
    return int(os.getenv("MAX_OCR_PAGES", "25"))


def _pdf_ocr_scale() -> float:
    return float(os.getenv("PDF_OCR_SCALE", "2.0"))


def _min_ocr_image_pixels() -> int:
    # Bỏ qua ảnh nhúng quá nhỏ (logo/icon) để khỏi tốn vision-call vô ích.
    return int(os.getenv("OCR_MIN_IMAGE_PIXELS", "64"))


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


def _vision_image(data: bytes, mime_type: str) -> VisionImage:
    return VisionImage(base64_data=base64.b64encode(data).decode("ascii"), mime_type=mime_type)


@dataclass
class _Page:
    """Nội dung một trang/đơn vị: text-layer (free) + ảnh cần OCR (vision).

    parse() merge `text` với kết quả OCR của `images` theo thứ tự. Trang chỉ có
    text ⇒ không gọi vision. Đây là cách hybrid hỗ trợ tài liệu text + image.
    """

    text: str = ""
    images: list[VisionImage] = field(default_factory=list)


@dataclass
class _ParseStep:
    pages: list[_Page] = field(default_factory=list)

    def total_images(self) -> int:
        return sum(len(page.images) for page in self.pages)


def _text_step(markdown: str) -> _ParseStep:
    return _ParseStep(pages=[_Page(text=markdown)])


def _read_text_file(path: Path) -> _ParseStep:
    _ensure_source_file(path)
    return _text_step(path.read_text(encoding="utf-8"))


class _HTMLToText(HTMLParser):
    _BLOCK_TAGS = {
        "address", "article", "aside", "blockquote", "br", "div", "dl", "dt", "dd",
        "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4",
        "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section",
        "table", "td", "th", "tr", "ul",
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


def _read_html_file(path: Path) -> _ParseStep:
    _ensure_source_file(path)
    parser = _HTMLToText()
    parser.feed(path.read_text(encoding="utf-8"))
    parser.close()
    return _text_step(parser.text())


def _read_docx_file(path: Path) -> _ParseStep:
    _ensure_source_file(path)
    with zipfile.ZipFile(path) as archive:
        try:
            document_xml = archive.read("word/document.xml")
        except KeyError as exc:
            raise ValueError(f"invalid docx file: {path}") from exc
        # Ảnh nhúng trong docx nằm ở word/media/* — gom để OCR (text + image).
        media_images: list[VisionImage] = []
        for name in archive.namelist():
            if not name.startswith("word/media/"):
                continue
            ext = name.rsplit(".", 1)[-1].lower()
            mime = _IMAGE_MIME_BY_EXT.get(ext)
            if mime is None:
                continue
            media_images.append(_vision_image(archive.read(name), mime))
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
    # Ảnh docx không có vị trí trong dòng text ⇒ gắn vào một "trang" cuối.
    return _ParseStep(pages=[_Page(text="\n\n".join(paragraphs), images=media_images)])


def _read_image_file(suffix: str):
    mime = _IMAGE_MIME_BY_SUFFIX[suffix]

    def reader(path: Path) -> _ParseStep:
        _ensure_source_file(path)
        return _ParseStep(pages=[_Page(images=[_vision_image(path.read_bytes(), mime)])])

    return reader


def _read_pdf_file(path: Path) -> _ParseStep:
    _ensure_source_file(path)
    try:
        import fitz
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("PyMuPDF is required to parse PDF sources") from exc
    min_pixels = _min_ocr_image_pixels()
    scale = _pdf_ocr_scale()
    pages: list[_Page] = []
    with fitz.open(path) as doc:
        for page in doc:
            text = _normalize_markdown(page.get_text("text"))
            images: list[VisionImage] = []
            if not text:
                # Trang scan / không có text-layer → rasterize cả trang cho vision.
                pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                images.append(_vision_image(pixmap.tobytes("png"), "image/png"))
            else:
                # Trang có chữ + ảnh nhúng → giữ text, vision riêng từng ảnh.
                for img in page.get_images(full=True):
                    xref = img[0]
                    info = doc.extract_image(xref)
                    mime = _IMAGE_MIME_BY_EXT.get((info.get("ext") or "").lower())
                    if mime is None:
                        continue
                    if info.get("width", 0) < min_pixels or info.get("height", 0) < min_pixels:
                        continue
                    images.append(_vision_image(info["image"], mime))
            pages.append(_Page(text=text, images=images))
    step = _ParseStep(pages=pages)
    if step.total_images() > _max_ocr_pages():
        raise ValueError(
            f"document requires OCR on {step.total_images()} images but exceeds "
            f"MAX_OCR_PAGES ({_max_ocr_pages()})"
        )
    return step


def _convert_with_markitdown(path: Path) -> _ParseStep:
    try:
        from markitdown import MarkItDown
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("MarkItDown with the required extras is not installed") from exc
    return _text_step(MarkItDown().convert(str(path)).text_content)


_SUFFIX_READERS = {
    "md": _read_text_file,
    "txt": _read_text_file,
    "html": _read_html_file,
    "htm": _read_html_file,
    "docx": _read_docx_file,
    "pdf": _read_pdf_file,
    "pptx": _convert_with_markitdown,
    "xls": _convert_with_markitdown,
    "xlsx": _convert_with_markitdown,
}


class LocalFileParser(Parser):
    """Đọc nguồn cục bộ → markdown qua I/O có guard.

    OCR/vision KHÔNG nằm ở adapter này: ảnh & scanned PDF được render thành
    `VisionImage` rồi đưa cho `image_text_extractor` (core_engine, qua AI
    gateway + OpenAI SDK). Hybrid theo trang: text-layer giữ nguyên (free), chỉ ảnh
    mới qua vision; tài liệu text+image được merge. Thiếu extractor mà gặp nguồn
    cần OCR ⇒ raise (fail-closed) thay vì âm thầm trả rỗng.
    """

    def __init__(
        self,
        *,
        max_workers: int = 2,
        image_text_extractor: ImageTextExtractor | None = None,
    ):
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="rag-parse",
        )
        self._image_text_extractor = image_text_extractor

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
        step = await loop.run_in_executor(self._executor, reader, path)

        if step.total_images() > 0 and self._image_text_extractor is None:
            raise RuntimeError(
                f"source {source_uri!r} requires OCR but no image_text_extractor is "
                "configured; OCR must go through the AI gateway"
            )

        parts: list[str] = []
        for page in step.pages:
            ocr_text = ""
            if page.images:
                ocr_text = await self._image_text_extractor.extract(page.images)
            merged = "\n\n".join(
                segment for segment in (page.text.strip(), ocr_text.strip()) if segment
            )
            if merged:
                parts.append(merged)

        return ParsedArtifact(
            markdown=_normalize_markdown("\n\n".join(parts)),
            source_uri=f"file://{path}",
        )

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _reader_for_suffix(self, suffix: str):
        reader = _SUFFIX_READERS.get(suffix)
        if reader is not None:
            return reader
        if suffix in _IMAGE_MIME_BY_SUFFIX:
            return _read_image_file(suffix)
        raise ValueError(f"unsupported file_type for local parser: {suffix}")
