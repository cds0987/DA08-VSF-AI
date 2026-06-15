from __future__ import annotations

import json
from pathlib import Path

from app.infrastructure.external.local_parser import (
    _DEFAULT_READER_IMPL,
    supported_suffixes,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST_PATH = (
    _REPO_ROOT / "src" / "document-service" / "app" / "supported_formats.json"
)


def _load_manifest_suffixes() -> dict[str, str]:
    data = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    return data["suffixes"]


def test_supported_suffixes_match_default_reader_impl() -> None:
    # supported_suffixes() phải phủ đúng _DEFAULT_READER_IMPL (mỗi impl có reader).
    assert set(supported_suffixes()) == set(_DEFAULT_READER_IMPL)


def test_manifest_in_sync_with_registry() -> None:
    # Manifest mà document-service đối chiếu phải khớp nguồn chân lý (rag-worker).
    assert _load_manifest_suffixes() == supported_suffixes(), (
        "supported_formats.json lệch với reader registry của rag-worker. "
        "Chạy: python src/rag-worker/scripts/gen_supported_formats.py"
    )
