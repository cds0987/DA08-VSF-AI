#!/usr/bin/env python3
"""Sinh manifest định dạng được hỗ trợ — nguồn: rag-worker reader registry.

Manifest (`src/document-service/app/supported_formats.json`) là HỢP ĐỒNG giữa
rag-worker (nguồn chân lý, parse được loại nào) và document-service (đối chiếu
allow_list của nó). KHÔNG sửa file JSON bằng tay — sửa reader trong local_parser
rồi chạy lại script này.

    python scripts/gen_supported_formats.py            # ghi đè manifest
    python scripts/gen_supported_formats.py --check     # CI: khác -> exit 1
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Cho phép import `app...` khi chạy script trực tiếp.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.infrastructure.external.local_parser import supported_suffixes  # noqa: E402

SCHEMA_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = (
    REPO_ROOT / "src" / "document-service" / "app" / "supported_formats.json"
)


def build_manifest() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "rag-worker/app/infrastructure/external/local_parser.py::supported_suffixes",
        "note": "Auto-generated. Run rag-worker/scripts/gen_supported_formats.py to update.",
        "suffixes": supported_suffixes(),
    }


def render(manifest: dict) -> str:
    return json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Chỉ so sánh, lệch -> exit 1 (dùng trong CI).",
    )
    args = parser.parse_args()

    content = render(build_manifest())

    if args.check:
        current = (
            MANIFEST_PATH.read_text(encoding="utf-8")
            if MANIFEST_PATH.exists()
            else ""
        )
        if current != content:
            print(
                "supported_formats.json lệch với reader registry. "
                "Chạy: python src/rag-worker/scripts/gen_supported_formats.py",
                file=sys.stderr,
            )
            return 1
        print("supported_formats.json in sync")
        return 0

    MANIFEST_PATH.write_text(content, encoding="utf-8")
    print(f"wrote {MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
