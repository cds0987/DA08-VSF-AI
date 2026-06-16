from __future__ import annotations

import asyncio
import base64
import csv
import os
import zipfile
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from app.domain.repositories.parser import ParsedArtifact, Parser
from core_engine.ai import VisionImage
from core_engine.ocr import ImageTextExtractor
from core_engine.registry import Registry

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


def _csv_row_to_markdown_line(row: list[str], width: int) -> str:
    cells = [cell.strip().replace("|", "\\|") for cell in row]
    if len(cells) < width:
        cells.extend([""] * (width - len(cells)))
    return "| " + " | ".join(cells[:width]) + " |"


def _read_csv_file(path: Path) -> _ParseStep:
    _ensure_source_file(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [[str(cell) for cell in row] for row in csv.reader(handle)]
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        return _text_step("")
    width = max(len(row) for row in rows)
    header = _csv_row_to_markdown_line(rows[0], width)
    separator = "| " + " | ".join(["---"] * width) + " |"
    body = [_csv_row_to_markdown_line(row, width) for row in rows[1:]]
    return _text_step("\n".join([header, separator, *body]))


class _HTMLToText(HTMLParser):
    _BLOCK_TAGS = {
        "address", "article", "aside", "blockquote", "br", "div", "dl", "dt", "dd",
        "fieldset", "figcaption", "figure", "footer", "form", "header", "hr", "li",
        "main", "nav", "ol", "p", "pre", "section", "table", "td", "th", "tr", "ul",
    }
    _HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        t = tag.lower()
        if t in self._HEADING_TAGS:
            self._parts.append(f"\n{'#' * int(t[1])} ")
        elif t in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._BLOCK_TAGS or tag.lower() in self._HEADING_TAGS:
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
    _w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    _heading_map = {
        "heading1": "#", "heading2": "##", "heading3": "###",
        "heading4": "####", "heading5": "#####", "heading6": "######",
    }
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", ns):
        style_el = paragraph.find("w:pPr/w:pStyle", ns)
        prefix = ""
        if style_el is not None:
            style_val = (style_el.get(f"{{{_w}}}val") or "").lower().replace(" ", "")
            prefix = _heading_map.get(style_val, "")
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
            paragraphs.append(f"{prefix} {text}" if prefix else text)
    # Ảnh docx không có vị trí trong dòng text ⇒ gắn vào một "trang" cuối.
    return _ParseStep(pages=[_Page(text="\n\n".join(paragraphs), images=media_images)])


def _read_image_file(path: Path) -> _ParseStep:
    # Suy MIME từ đuôi file (đường dẫn có thể là file tạm `.s3-xxx.png`).
    suffix = path.suffix.lstrip(".").lower()
    mime = _IMAGE_MIME_BY_SUFFIX.get(suffix)
    if mime is None:
        raise ValueError(f"unsupported image suffix for local parser: {suffix}")
    _ensure_source_file(path)
    return _ParseStep(pages=[_Page(images=[_vision_image(path.read_bytes(), mime)])])


def _make_pymupdf_reader(params: Mapping[str, Any]) -> Reader:
    # Param override env (backward-compatible: thiếu param thì dùng env cũ).
    min_pixels = int(params.get("min_image_pixels", _min_ocr_image_pixels()))
    scale = float(params.get("ocr_scale", _pdf_ocr_scale()))
    max_ocr_pages = int(params.get("max_ocr_pages", _max_ocr_pages()))

    def reader(path: Path) -> _ParseStep:
        _ensure_source_file(path)
        try:
            import fitz
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError("PyMuPDF is required to parse PDF sources") from exc
        pages: list[_Page] = []
        with fitz.open(path) as doc:
            for page in doc:
                text = _normalize_markdown(page.get_text("markdown"))
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
        if step.total_images() > max_ocr_pages:
            raise ValueError(
                f"document requires OCR on {step.total_images()} images but exceeds "
                f"MAX_OCR_PAGES ({max_ocr_pages})"
            )
        return step

    return reader


def _make_pypdf_reader(params: Mapping[str, Any]) -> Reader:
    # Text-only: pypdf KHÔNG rasterize trang scan / KHÔNG trích ảnh nhúng → không OCR.
    # Trang không có text-layer ra rỗng (PDF scan sẽ vỡ ở EmptyIngestResultError).
    del params

    def reader(path: Path) -> _ParseStep:
        _ensure_source_file(path)
        try:
            from pypdf import PdfReader
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError("pypdf is required for the 'pypdf' reader") from exc
        reader_obj = PdfReader(str(path))
        pages = [
            _Page(text=_normalize_markdown(page.extract_text() or ""))
            for page in reader_obj.pages
        ]
        return _ParseStep(pages=pages)

    return reader


def _convert_with_markitdown(path: Path) -> _ParseStep:
    try:
        from markitdown import MarkItDown
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("MarkItDown with the required extras is not installed") from exc
    return _text_step(MarkItDown().convert(str(path)).text_content)


# --- Reader registry: engine giải mã MỘT định dạng (suffix-agnostic) --------- #
# Cùng primitive Registry với parser/chunker/vectorstore. Reader CHỈ trả _ParseStep
# (text + ảnh thô); guard SOURCE_ROOT + OCR-qua-gateway + merge vẫn nằm ở
# LocalFileParser → bất biến bảo mật/OCR được giữ dù đổi reader. Bên thứ ba cắm định
# dạng mới qua entry-point `rag_worker.reader` (vd .epub) KHÔNG sửa core.
Reader = Callable[[Path], "_ParseStep"]
ReaderFactory = Callable[[Mapping[str, Any]], Reader]

_READER_REGISTRY: Registry[ReaderFactory] = Registry(
    "reader", entry_point_group="rag_worker.reader"
)
_READER_REGISTRY.register("text", lambda params: _read_text_file)
_READER_REGISTRY.register("csv", lambda params: _read_csv_file)
_READER_REGISTRY.register("html_strip", lambda params: _read_html_file)
_READER_REGISTRY.register("docx_xml", lambda params: _read_docx_file)
_READER_REGISTRY.register("image", lambda params: _read_image_file)
_READER_REGISTRY.register("markitdown", lambda params: _convert_with_markitdown)
_READER_REGISTRY.register("pymupdf", _make_pymupdf_reader)
_READER_REGISTRY.register("pypdf", _make_pypdf_reader)

# Bản đồ suffix -> impl MẶC ĐỊNH (khi config.parser.readers KHÔNG khai báo suffix đó).
# Giữ y hệt hành vi cũ để backward-compatible.
_DEFAULT_READER_IMPL: dict[str, str] = {
    "md": "text",
    "txt": "text",
    "csv": "csv",
    "html": "html_strip",
    "htm": "html_strip",
    "docx": "docx_xml",
    "pdf": "pymupdf",
    "pptx": "markitdown",
    "xls": "markitdown",
    "xlsx": "markitdown",
    **{suffix: "image" for suffix in _IMAGE_MIME_BY_SUFFIX},
}


def register_reader(
    name: str, factory: ReaderFactory, *, override: bool = False
) -> None:
    """Đăng ký engine giải mã định dạng. Trùng tên mà ko override -> raise."""
    _READER_REGISTRY.register(name, factory, override=override)


def supported_suffixes() -> dict[str, str]:
    """Bản đồ suffix -> reader-impl mà local parser giải mã được — NGUỒN CHÂN LÝ.

    Một suffix CHỈ được tính là supported khi impl của nó thực sự tồn tại trong
    reader registry (gồm cả reader cắm thêm qua entry-point `rag_worker.reader`),
    nên hàm phản ánh đúng cơ chế đăng ký linh hoạt của rag-worker. Document-service
    đối chiếu allow_list của nó với manifest sinh từ hàm này — xem
    scripts/gen_supported_formats.py và test_parser_parity.py.
    """
    available = set(_READER_REGISTRY.available())
    resolved: dict[str, str] = {}
    for suffix, impl in _DEFAULT_READER_IMPL.items():
        if impl not in available:
            raise RuntimeError(
                f"reader impl {impl!r} cho suffix {suffix!r} chưa đăng ký trong registry; "
                f"có: {sorted(available)}"
            )
        resolved[suffix] = impl
    return dict(sorted(resolved.items()))


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
        readers_config: Mapping[str, Any] | None = None,
    ):
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="rag-parse",
        )
        self._image_text_extractor = image_text_extractor
        # suffix -> (impl, params). Mỗi spec là ReaderConfig (pydantic) hoặc dict.
        # Thiếu suffix nào thì rơi về _DEFAULT_READER_IMPL.
        self._readers_config: dict[str, tuple[str, Mapping[str, Any]]] = {}
        for suffix, spec in (readers_config or {}).items():
            impl = getattr(spec, "impl", None) if not isinstance(spec, Mapping) else spec.get("impl")
            params = (
                getattr(spec, "params", {}) if not isinstance(spec, Mapping)
                else spec.get("params", {})
            )
            if not impl:
                raise ValueError(f"reader config for {suffix!r} must define an impl")
            self._readers_config[suffix.lower().lstrip(".")] = (impl, dict(params or {}))

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
                page.images.clear()
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

    def _reader_for_suffix(self, suffix: str) -> Reader:
        override = self._readers_config.get(suffix)
        if override is not None:
            impl, params = override
        else:
            impl = _DEFAULT_READER_IMPL.get(suffix)
            if impl is None:
                raise ValueError(f"unsupported file_type for local parser: {suffix}")
            params = {}
        factory = _READER_REGISTRY.get(impl)
        return factory(dict(params))
