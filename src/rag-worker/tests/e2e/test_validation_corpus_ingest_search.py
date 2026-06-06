"""E2E: real source files -> real LocalFileParser -> engine -> Qdrant :memory: -> payload.

Bổ sung cho `test_inmemory_ingest_search.py` (chỉ ingest inline markdown): ở đây ta
ingest **file thật** trên đĩa (`txt/md/html/docx/pdf`) qua **parser thật**
(`LocalFileParser`) — bài test này phủ luôn nhánh trích xuất text, bóc HTML, đi
XML của docx và đọc text-layer PDF.

Corpus + golden query nằm trong `eval/validation/` và được lái hoàn toàn bằng
`manifest.json` (thêm file + entry là đủ, không sửa code). Corpus cố tình chỉ gồm
tài liệu DẠNG TEXT (không OCR) để suite xanh offline, không cần AI gateway.

Offline provider dùng embedding hash (không ngữ nghĩa): bài test kiểm PLUMBING
(file -> parse -> ingest -> payload contract + lineage), không kiểm chất lượng search.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.infrastructure.external.local_parser import LocalFileParser
from core_engine import IngestInput, OfflineProvider, build_engine
from core_engine.ai import get_ai_provider, reset_ai_provider
from core_engine.vectorstore import VectorStoreConfig
from tests.e2e._vector_helpers import payloads_for_document

VALIDATION_DIR = Path(__file__).resolve().parents[2] / "eval" / "validation"
MANIFEST_PATH = VALIDATION_DIR / "manifest.json"


def _load_manifest() -> list[dict]:
    documents = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["documents"]
    assert documents, "validation manifest must list at least one document"
    return documents


def _build_inmemory_engine():
    """Offline by default (plumbing check); real provider when RAG_EVAL_REAL_PROVIDER=1.

    Real mode uses the env-configured AI gateway (OPENAI_API_KEY / EMBED_BASE_URL /
    EMBED_DIMENSION) so retrieval is semantic, not just lexical. Vector store stays
    Qdrant :memory: either way — the corpus is small and we only assert routing/recall.
    """
    vector_config = VectorStoreConfig(provider="qdrant", url="")  # rỗng => in_process :memory:
    if os.getenv("RAG_EVAL_REAL_PROVIDER", "").strip() == "1":
        try:
            reset_ai_provider()
            return build_engine(provider=get_ai_provider(), vector_config=vector_config, caption=False)
        except (ValueError, ModuleNotFoundError) as exc:
            pytest.skip(f"real-provider eval not configured: {exc}")
    return build_engine(provider=OfflineProvider(256), vector_config=vector_config, caption=False)


@pytest.fixture
def parser(monkeypatch: pytest.MonkeyPatch) -> LocalFileParser:
    # Parser chỉ cho đọc trong allow-list SOURCE_ROOT; trỏ vào corpus validation.
    monkeypatch.setenv("SOURCE_ROOT", str(VALIDATION_DIR))
    parser = LocalFileParser(max_workers=2)  # corpus text-only => không cần OCR extractor
    yield parser
    parser.close()


async def _ingest_corpus(engine, parser: LocalFileParser, manifest: list[dict]) -> None:
    for entry in manifest:
        try:
            artifact = await parser.parse(
                document_id=entry["document_id"],
                file_type=entry["file_type"],
                source_uri=f"local://{entry['file']}",
            )
        except ImportError as exc:
            pytest.skip(
                f"validation corpus requires optional parser dependency for {entry['file_type']}: {exc}"
            )
        assert artifact.markdown.strip(), f"parser returned empty markdown for {entry['file']}"
        chunk_count = await engine.ingest(
            IngestInput(
                document_id=entry["document_id"],
                document_name=entry["document_name"],
                file_type=entry["file_type"],
                markdown=artifact.markdown,
                source_uri=artifact.source_uri,
                artifact_uri=f"artifact://{entry['document_id']}",
                correlation_id=f"val:{entry['document_id']}",
            )
        )
        assert chunk_count > 0, f"ingest produced no chunks for {entry['file']}"


@pytest.mark.asyncio
async def test_validation_corpus_files_ingest_and_persist_payloads(parser: LocalFileParser) -> None:
    manifest = _load_manifest()
    engine = _build_inmemory_engine()
    assert engine.vectors.config.deployment == "in_process"

    await _ingest_corpus(engine, parser, manifest)

    for entry in manifest:
        payloads = payloads_for_document(engine, entry["document_id"])
        assert payloads, f"no payloads persisted for {entry['document_id']!r}"
        assert all(payload["document_name"] == entry["document_name"] for payload in payloads)
        assert all(payload["artifact_uri"] == f"artifact://{entry['document_id']}" for payload in payloads)
        assert all(payload["source_uri"].endswith(entry["file"]) for payload in payloads)
        joined = " ".join(payload["parent_text"] for payload in payloads)
        assert entry["expect_keyword"] in joined.lower()
