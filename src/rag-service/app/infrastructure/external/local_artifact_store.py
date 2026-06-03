from __future__ import annotations

import asyncio
import os
from pathlib import Path

from app.domain.repositories.artifact_store import ArtifactStore


def _artifact_root() -> Path:
    raw = os.getenv(
        "ARTIFACT_ROOT",
        str(Path("src/rag-service/.artifacts").resolve()),
    )
    return Path(raw).resolve()


def _artifact_path(document_id: str) -> Path:
    safe = document_id.replace("/", "_").replace("\\", "_")
    return _artifact_root() / f"{safe}.md"


def _resolve_artifact_path(artifact_uri: str) -> Path:
    if not artifact_uri.startswith("artifact://"):
        raise ValueError(f"unsupported artifact URI: {artifact_uri}")
    path = Path(artifact_uri[len("artifact://") :]).resolve()
    root = _artifact_root()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"artifact path outside ARTIFACT_ROOT: {path}") from exc
    return path


def _write(path: Path, markdown: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class LocalArtifactStore(ArtifactStore):
    async def write_markdown(self, document_id: str, markdown: str) -> str:
        path = _artifact_path(document_id)
        await asyncio.to_thread(_write, path, markdown)
        return f"artifact://{path}"

    async def read_markdown(self, artifact_uri: str) -> str:
        path = _resolve_artifact_path(artifact_uri)
        return await asyncio.to_thread(_read, path)
