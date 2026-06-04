"""E2E (gated): image/scanned sources -> real LocalFileParser + vision OCR -> engine -> search.

Anh em với `test_validation_corpus_ingest_search.py`, nhưng cho nhánh KHÔNG có text-layer:
ảnh (`png/jpg`), PDF scan (rasterize), và docx có ảnh nhúng — chữ chỉ nằm trong ảnh nên
parser phải đi qua AI gateway (`ProviderImageTextExtractor`) để OCR ra markdown.

Vì cần vision LLM thật, bài test này GATED: skip trừ khi `RAG_EVAL_REAL_PROVIDER=1` và
provider cấu hình được (OPENAI_API_KEY / EMBED_BASE_URL...). Đây là lý do corpus OCR tách
khỏi `manifest.json` (suite offline) — xem README trong eval/validation.

Lái hoàn toàn bằng `manifest_ocr.json`: thêm file + entry là đủ, không sửa code.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.infrastructure.external.local_parser import LocalFileParser
from core_engine import IngestInput, build_engine
from core_engine.ai import get_ai_provider, reset_ai_provider
from core_engine.ocr import ProviderImageTextExtractor
from core_engine.vectorstore import VectorStoreConfig

VALIDATION_DIR = Path(__file__).resolve().parents[2] / "eval" / "validation"
MANIFEST_PATH = VALIDATION_DIR / "manifest_ocr.json"


def _load_manifest() -> list[dict]:
    documents = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["documents"]
    assert documents, "OCR validation manifest must list at least one document"
    return documents


def _require_real_provider():
    """Provider thật cho cả OCR (vision) lẫn embedding; skip sạch nếu chưa cấu hình."""
    if os.getenv("RAG_EVAL_REAL_PROVIDER", "").strip() != "1":
        pytest.skip("OCR corpus needs a vision provider; set RAG_EVAL_REAL_PROVIDER=1 to run")
    try:
        reset_ai_provider()
        provider = get_ai_provider()
    except (ValueError, ModuleNotFoundError) as exc:
        pytest.skip(f"real-provider eval not configured: {exc}")
    if provider.name == "offline":
        pytest.skip("offline provider cannot OCR images; configure a real vision provider")
    return provider


@pytest.fixture
def provider():
    return _require_real_provider()


@pytest.fixture
def parser(provider, monkeypatch: pytest.MonkeyPatch) -> LocalFileParser:
    monkeypatch.setenv("SOURCE_ROOT", str(VALIDATION_DIR))
    # Parser CÓ extractor: corpus này cố tình chỉ chứa chữ trong ảnh => phải OCR.
    parser = LocalFileParser(
        max_workers=2,
        image_text_extractor=ProviderImageTextExtractor(provider),
    )
    yield parser
    parser.close()


@pytest.mark.asyncio
async def test_ocr_corpus_files_ingest_and_retrieve_top_hit(provider, parser: LocalFileParser) -> None:
    manifest = _load_manifest()
    vector_config = VectorStoreConfig(provider="qdrant", url="")  # in_process :memory:
    engine = build_engine(provider=provider, vector_config=vector_config, caption=False)

    for entry in manifest:
        artifact = await parser.parse(
            document_id=entry["document_id"],
            file_type=entry["file_type"],
            source_uri=f"local://{entry['file']}",
        )
        assert artifact.markdown.strip(), f"OCR returned empty markdown for {entry['file']}"
        chunk_count = await engine.ingest(
            IngestInput(
                document_id=entry["document_id"],
                document_name=entry["document_name"],
                file_type=entry["file_type"],
                markdown=artifact.markdown,
                source_uri=artifact.source_uri,
                artifact_uri=f"artifact://{entry['document_id']}",
                correlation_id=f"ocr:{entry['document_id']}",
            )
        )
        assert chunk_count > 0, f"ingest produced no chunks for {entry['file']}"

    for entry in manifest:
        results = await engine.search(entry["query"], top_k=5, rerank_threshold=0.0)
        assert results, f"no result for query={entry['query']!r}"
        assert results[0].document_id == entry["document_id"], (
            f"query {entry['query']!r} expected top doc {entry['document_id']!r}, "
            f"got {results[0].document_id!r}"
        )
        joined = " ".join(r.content for r in results if r.document_id == entry["document_id"])
        # Keyword chỉ tồn tại trong ảnh => có nó nghĩa là OCR thực sự đọc được nội dung.
        assert entry["expect_keyword"].lower() in joined.lower(), (
            f"OCR output for {entry['file']} missing expected keyword "
            f"{entry['expect_keyword']!r}"
        )
