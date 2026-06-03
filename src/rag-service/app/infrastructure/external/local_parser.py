from __future__ import annotations

import asyncio
import os
from pathlib import Path

from app.domain.repositories.parser import ParsedArtifact, Parser


def _allowed_source_root() -> Path:
    raw = os.getenv("SOURCE_ROOT", os.getcwd())
    return Path(raw).resolve()


def _max_source_size_bytes() -> int:
    return int(os.getenv("MAX_SOURCE_SIZE_BYTES", str(10 * 1024 * 1024)))


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


def _read_text_file(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"source file not found: {path}")
    size = path.stat().st_size
    if size > _max_source_size_bytes():
        raise ValueError(f"source too large: {size} bytes > MAX_SOURCE_SIZE_BYTES")
    return path.read_text(encoding="utf-8")


def _read_pdf_file(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"source file not found: {path}")
    size = path.stat().st_size
    if size > _max_source_size_bytes():
        raise ValueError(f"source too large: {size} bytes > MAX_SOURCE_SIZE_BYTES")
    try:
        import fitz
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("PyMuPDF is required to parse PDF sources") from exc
    with fitz.open(path) as doc:
        return "\n".join(page.get_text("text") for page in doc)


class LocalFileParser(Parser):
    async def parse(
        self,
        *,
        document_id: str,
        file_type: str,
        source_uri: str,
    ) -> ParsedArtifact:
        path = _resolve_local_source(source_uri)
        suffix = file_type.lower().strip(".")
        if suffix in {"md", "txt"}:
            markdown = await asyncio.to_thread(_read_text_file, path)
        elif suffix == "pdf":
            markdown = await asyncio.to_thread(_read_pdf_file, path)
        else:
            raise ValueError(f"unsupported file_type for local parser: {file_type}")
        return ParsedArtifact(markdown=markdown, source_uri=f"file://{path}")
