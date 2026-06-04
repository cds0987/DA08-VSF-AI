"""E2E: real source files -> real LocalFileParser -> engine -> Qdrant :memory: -> search.

Bổ sung cho `test_inmemory_ingest_search.py` (chỉ ingest inline markdown): ở đây ta
ingest **file thật** trên đĩa (`txt/md/html/docx/pdf`) qua **parser thật**
(`LocalFileParser`) — bài test này phủ luôn nhánh trích xuất text, bóc HTML, đi
XML của docx và đọc text-layer PDF.

Corpus + golden query nằm trong `eval/validation/` và được lái hoàn toàn bằng
`manifest.json` (thêm file + entry là đủ, không sửa code). Corpus cố tình chỉ gồm
tài liệu DẠNG TEXT (không OCR) để suite xanh offline, không cần AI gateway.

Offline provider dùng embedding hash (không ngữ nghĩa) + rerank lexical với
`rerank_threshold=0.0`: bài test kiểm PLUMBING (file -> parse -> ingest -> search ->
contract fields + đúng tài liệu top-hit), không kiểm chất lượng — chất lượng cần
provider thật (xem README trong eval/validation).
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
        artifact = await parser.parse(
            document_id=entry["document_id"],
            file_type=entry["file_type"],
            source_uri=f"local://{entry['file']}",
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
async def test_validation_corpus_files_ingest_and_retrieve_top_hit(parser: LocalFileParser) -> None:
    manifest = _load_manifest()
    engine = _build_inmemory_engine()
    assert engine.vectors.config.deployment == "in_process"

    await _ingest_corpus(engine, parser, manifest)

    for entry in manifest:
        correlation_id = f"val:query:{entry['document_id']}"
        results = await engine.search(
            entry["query"],
            top_k=5,
            rerank_threshold=0.0,
            correlation_id=correlation_id,
        )
        assert results, f"no result for query={entry['query']!r}"

        top = results[0]
        # Đúng tài liệu được lái lên top-hit (lexical rerank trên corpus tách bạch từ vựng).
        assert top.document_id == entry["document_id"], (
            f"query {entry['query']!r} expected top doc {entry['document_id']!r}, "
            f"got {top.document_id!r}"
        )
        # Contract fields đầy đủ + lineage truy được về nguồn/artifact.
        assert top.correlation_id == correlation_id
        assert top.display_name == entry["document_name"]
        assert top.unit_id.startswith(f"{entry['document_id']}::p")
        assert top.content
        assert top.lineage.source_uri.endswith(entry["file"])
        assert top.lineage.artifact_uri == f"artifact://{entry['document_id']}"
        # Câu trả lời mong đợi thực sự nằm trong nội dung lấy ra.
        joined = " ".join(r.content for r in results if r.document_id == entry["document_id"])
        assert entry["expect_keyword"] in joined.lower()


@pytest.mark.asyncio
async def test_validation_corpus_no_answer_for_ungrounded_query(parser: LocalFileParser) -> None:
    manifest = _load_manifest()
    engine = _build_inmemory_engine()
    await _ingest_corpus(engine, parser, manifest)

    # Threshold > 1.0 => không kết quả nào vượt ngưỡng => no-answer (không bịa).
    results = await engine.search(
        "what is the quarterly revenue forecast for the marketing division",
        top_k=5,
        rerank_threshold=1.01,
        correlation_id="val:no-answer",
    )
    assert results == []
