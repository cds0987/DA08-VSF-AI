"""E2E (opt-in): an S3-compatible object source -> parser -> engine -> search.

Prototype for the not-yet-ratified S3 change-detector (gap.md #17 / decision D1).
Works against any store that speaks the S3 API — Google Cloud Storage (interop/XML
API), Cloudflare R2, AWS S3, MinIO — so it proves the "scan a bucket -> ingest each
object -> search" loop runs end-to-end against a REAL object store, WITHOUT committing
to any adapter design: objects are downloaded into a temp dir that acts as SOURCE_ROOT
and fed through the existing `LocalFileParser`. The only new dependency is boto3, used
only here (not in the service image).

Opt-in: skipped unless S3_* env is set (R2_* accepted as fallback; load .env first).
Provider is offline by default; set RAG_EVAL_REAL_PROVIDER=1 to retrieve with the real
AI gateway.

Run:
    # after filling S3_* in .env and uploading the corpus once:
    #   python scripts/upload_validation_to_r2.py
    python -m pytest tests/e2e/test_r2_source_ingest_search.py -v
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

def _env(name: str, *fallbacks: str, default: str = "") -> str:
    for candidate in (name, *fallbacks):
        value = os.getenv(candidate, "").strip()
        if value:
            return value
    return default


# Endpoint is optional (empty => AWS default); access key + secret + bucket are required.
def _s3_env_ready() -> bool:
    return all(
        _env(*names)
        for names in (
            ("S3_ACCESS_KEY_ID", "R2_ACCESS_KEY_ID"),
            ("S3_SECRET_ACCESS_KEY", "R2_SECRET_ACCESS_KEY"),
            ("S3_BUCKET", "R2_BUCKET"),
        )
    )


pytestmark = pytest.mark.skipif(
    not _s3_env_ready(),
    reason="S3_* env not set; set S3_ACCESS_KEY_ID/S3_SECRET_ACCESS_KEY/S3_BUCKET (+S3_ENDPOINT_URL) to run",
)


def _bucket() -> str:
    return _env("S3_BUCKET", "R2_BUCKET")


def _prefix() -> str:
    return _env("S3_PREFIX", "R2_PREFIX", default="validation/")


def _r2_client():
    boto3 = pytest.importorskip("boto3", reason="boto3 not installed")
    from botocore.client import Config

    return boto3.client(
        "s3",
        endpoint_url=_env("S3_ENDPOINT_URL", "R2_ENDPOINT_URL") or None,  # None => AWS default
        aws_access_key_id=_env("S3_ACCESS_KEY_ID", "R2_ACCESS_KEY_ID"),
        aws_secret_access_key=_env("S3_SECRET_ACCESS_KEY", "R2_SECRET_ACCESS_KEY"),
        region_name=_env("S3_REGION", default="auto"),
        # Disable botocore's default CRC32 request checksum: GCS/R2/MinIO reject the
        # flexible-checksum headers and fail PutObject with SignatureDoesNotMatch.
        config=Config(
            signature_version="s3v4",
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def _load_manifest() -> list[dict]:
    documents = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["documents"]
    assert documents, "validation manifest must list at least one document"
    return documents


def _build_engine():
    vector_config = VectorStoreConfig(provider="qdrant", url="")  # in_process :memory:
    if os.getenv("RAG_EVAL_REAL_PROVIDER", "").strip() == "1":
        try:
            reset_ai_provider()
            return build_engine(provider=get_ai_provider(), vector_config=vector_config, caption=False)
        except (ValueError, ModuleNotFoundError) as exc:
            pytest.skip(f"real-provider eval not configured: {exc}")
    return build_engine(provider=OfflineProvider(256), vector_config=vector_config, caption=False)


@pytest.fixture
def source_root(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # Parser only reads under SOURCE_ROOT; objects are downloaded here from R2.
    monkeypatch.setenv("SOURCE_ROOT", str(tmp_path))
    return tmp_path


def test_r2_bucket_lists_the_uploaded_corpus() -> None:
    """Sanity: the corpus was uploaded (run scripts/upload_validation_to_r2.py first)."""
    bucket = _bucket()
    prefix = _prefix()
    s3 = _r2_client()
    listing = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
    keys = {obj["Key"] for obj in listing.get("Contents", [])}
    expected = {f"{prefix}{entry['file']}" for entry in _load_manifest()}
    missing = expected - keys
    assert not missing, (
        f"missing objects in R2 (run scripts/upload_validation_to_r2.py): {sorted(missing)}"
    )


@pytest.mark.asyncio
async def test_r2_objects_ingest_and_retrieve_top_hit(source_root: Path) -> None:
    manifest = _load_manifest()
    bucket = _bucket()
    prefix = _prefix()
    s3 = _r2_client()

    engine = _build_engine()
    assert engine.vectors.config.deployment == "in_process"
    parser = LocalFileParser(max_workers=2)  # corpus text-only => no OCR extractor
    try:
        # "Scan the bucket": download each object then ingest via the existing parser.
        for entry in manifest:
            key = f"{prefix}{entry['file']}"
            local_path = source_root / entry["file"]
            s3.download_file(bucket, key, str(local_path))

            artifact = await parser.parse(
                document_id=entry["document_id"],
                file_type=entry["file_type"],
                source_uri=f"local://{entry['file']}",
            )
            assert artifact.markdown.strip(), f"empty markdown parsed from R2 object {key}"
            chunk_count = await engine.ingest(
                IngestInput(
                    document_id=entry["document_id"],
                    document_name=entry["document_name"],
                    file_type=entry["file_type"],
                    markdown=artifact.markdown,
                    # Lineage records the real object address it came from.
                    source_uri=f"s3://{bucket}/{key}",
                    artifact_uri=f"artifact://{entry['document_id']}",
                    correlation_id=f"r2:{entry['document_id']}",
                )
            )
            assert chunk_count > 0, f"ingest produced no chunks for R2 object {key}"
    finally:
        parser.close()

    for entry in manifest:
        correlation_id = f"r2:query:{entry['document_id']}"
        results = await engine.search(
            entry["query"], top_k=5, rerank_threshold=0.0, correlation_id=correlation_id
        )
        assert results, f"no result for query={entry['query']!r}"
        top = results[0]
        assert top.document_id == entry["document_id"], (
            f"query {entry['query']!r} expected {entry['document_id']!r}, got {top.document_id!r}"
        )
        assert top.correlation_id == correlation_id
        # Lineage points back at the R2 object, proving source provenance survives ingest.
        assert top.lineage.source_uri == f"s3://{bucket}/{prefix}{entry['file']}"
        joined = " ".join(r.content for r in results if r.document_id == entry["document_id"])
        assert entry["expect_keyword"] in joined.lower()
