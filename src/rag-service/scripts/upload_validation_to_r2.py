#!/usr/bin/env python
"""Upload the eval/validation corpus to any S3-compatible object store.

One-time setup for the object-source prototype test
(`tests/e2e/test_r2_source_ingest_search.py`). Works with any store that speaks the
S3 API — Google Cloud Storage (interoperability/XML API), Cloudflare R2, AWS S3,
MinIO — by pointing boto3 at the store's endpoint. Reads S3_* from the environment
(R2_* accepted as fallback). Load .env first.

Endpoints:
    GCS : https://storage.googleapis.com        (HMAC key: Console > Cloud Storage > Settings > Interoperability)
    R2  : https://<ACCOUNT_ID>.r2.cloudflarestorage.com
    AWS : leave S3_ENDPOINT_URL empty (uses the default AWS endpoint)

Usage (env already loaded):
    python scripts/upload_validation_to_r2.py
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
from pathlib import Path

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

VALIDATION_DIR = Path(__file__).resolve().parents[1] / "eval" / "validation"


def _env(name: str, *fallbacks: str, default: str = "") -> str:
    for candidate in (name, *fallbacks):
        value = os.getenv(candidate, "").strip()
        if value:
            return value
    return default


def _require(name: str, *fallbacks: str) -> str:
    value = _env(name, *fallbacks)
    if not value:
        sys.exit(f"missing required env var: {name} (load .env first)")
    return value


def _client():
    endpoint = _env("S3_ENDPOINT_URL", "R2_ENDPOINT_URL") or None  # None => AWS default
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=_require("S3_ACCESS_KEY_ID", "R2_ACCESS_KEY_ID"),
        aws_secret_access_key=_require("S3_SECRET_ACCESS_KEY", "R2_SECRET_ACCESS_KEY"),
        region_name=_env("S3_REGION", default="auto"),
        # Disable botocore's default CRC32 request checksum: GCS/R2/MinIO reject the
        # flexible-checksum headers and fail PutObject with SignatureDoesNotMatch.
        config=Config(
            signature_version="s3v4",
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def main() -> None:
    bucket = _require("S3_BUCKET", "R2_BUCKET")
    prefix = _env("S3_PREFIX", "R2_PREFIX", default="validation/")
    s3 = _client()

    # Ensure the bucket exists. create_bucket via the S3 API is not supported on every
    # store (e.g. GCS wants the bucket made in the console), so creation is best-effort.
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError:
        print(f"bucket {bucket!r} not reachable, attempting to create ...")
        try:
            s3.create_bucket(Bucket=bucket)
        except ClientError as exc:
            sys.exit(
                f"could not create bucket {bucket!r} via S3 API ({exc.response['Error'].get('Code')}). "
                "Create it in your provider console, then re-run."
            )

    documents = json.loads((VALIDATION_DIR / "manifest.json").read_text(encoding="utf-8"))["documents"]
    for entry in documents:
        path = VALIDATION_DIR / entry["file"]
        if not path.is_file():
            sys.exit(f"corpus file missing: {path}")
        key = f"{prefix}{entry['file']}"
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        s3.upload_file(str(path), bucket, key, ExtraArgs={"ContentType": content_type})
        print(f"  uploaded s3://{bucket}/{key}  ({path.stat().st_size} bytes)")

    print(f"\ndone: {len(documents)} object(s) under s3://{bucket}/{prefix}")


if __name__ == "__main__":
    main()
