"""Đối chiếu allow_list của document-service với khả năng parse của rag-worker.

rag-worker là NGUỒN CHÂN LÝ: `supported_formats.json` được sinh tự động từ reader
registry của rag-worker (xem rag-worker/scripts/gen_supported_formats.py). Document
service KHÔNG tự khai báo danh sách loại file — nó đọc manifest rồi GIAO với
allow_list chính sách (linh hoạt qua ENV `DOC_ALLOWED_EXTENSIONS`).

Bất biến: tập loại file document-service chấp nhận ⊆ tập rag-worker parse được.
Cấu hình allow_list chứa loại rag-worker không parse được -> fail-fast (lệch hợp đồng),
thay vì cho upload file mà ingest sẽ chết về sau.
"""
from __future__ import annotations

import json
from pathlib import Path

# app/application/use_cases/documents/ -> app/
_MANIFEST_PATH = Path(__file__).resolve().parents[3] / "supported_formats.json"


def _normalize(suffix: str) -> str:
    return suffix.strip().lower().lstrip(".")


def _load_rag_supported() -> frozenset[str]:
    data = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    suffixes = data.get("suffixes", {})
    if not suffixes:
        raise RuntimeError(f"{_MANIFEST_PATH} không có 'suffixes' — manifest hỏng?")
    return frozenset(_normalize(s) for s in suffixes)


# Loại file rag-worker parse được — nạp một lần lúc import.
RAG_SUPPORTED_EXTENSIONS: frozenset[str] = _load_rag_supported()


def resolve_allowed_extensions(allow_list: set[str] | None) -> frozenset[str]:
    """Giao allow_list (chính sách) với khả năng parse của rag-worker.

    allow_list rỗng/None -> cho phép TẤT CẢ loại rag-worker support (mặc định).
    allow_list có loại NGOÀI manifest -> ValueError (cấu hình sai, fail-fast).
    """
    if not allow_list:
        return RAG_SUPPORTED_EXTENSIONS
    normalized = {_normalize(s) for s in allow_list if s.strip()}
    unknown = normalized - RAG_SUPPORTED_EXTENSIONS
    if unknown:
        raise ValueError(
            "DOC_ALLOWED_EXTENSIONS chứa loại rag-worker KHÔNG parse được: "
            f"{sorted(unknown)}. Hỗ trợ: {sorted(RAG_SUPPORTED_EXTENSIONS)}. "
            "Thêm reader trong rag-worker rồi chạy gen_supported_formats.py, "
            "hoặc bỏ loại đó khỏi allow_list."
        )
    return frozenset(normalized)
