from __future__ import annotations

import asyncio
from pathlib import Path

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

        parsed = await LocalFileParser().parse(
            document_id="doc-1",
            file_type="md",
            source_uri="local://guide.md",
        )

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

        with pytest.raises(ValueError, match="outside SOURCE_ROOT"):
            await LocalFileParser().parse(
                document_id="doc-1",
                file_type="md",
                source_uri=f"file://{outside.resolve()}",
            )

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
