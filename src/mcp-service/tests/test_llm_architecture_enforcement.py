"""GATE KIẾN TRÚC LLM (mcp-service) — ép mọi call AI đi qua lớp route-aware (có base_url)
để KHỐNG CHẾ HẾT: trỏ base_url -> ai-router là cân bằng key + cost + observability.

Bối cảnh: mcp-service rerank qua LLM (embed + vector search ĐÃ chuyển sang rag-worker).
Nếu dev mới tạo AsyncOpenAI() KHÔNG base_url -> khoá cứng OpenAI, BYPASS ai-router (xem
observability-plan §11.1). 2 gate (mirror query-service):

  GATE 1 : SDK call (embeddings/chat.completions/responses .create) CHỈ ở allowlist provider.
  GATE 1b: file tạo AsyncOpenAI PHẢI truyền base_url (route-aware) — không hardcode OpenAI.
"""
from __future__ import annotations

import re
from pathlib import Path

_APP = Path(__file__).resolve().parents[1] / "app"

# CHỈ các file provider tập trung được phép gọi SDK / tạo AsyncOpenAI (đều nhận base_url
# từ config -> trỏ ai-router được). Thêm file = quyết định kiến trúc CÓ Ý THỨC.
_SDK_ALLOWLIST = {
    "core/rerank.py",      # LlmReranker: chat.completions.create, base_url từ rerank_base_url
}

_SDK_CALL_RE = re.compile(r"\.(responses|chat\.completions|embeddings)\.create\s*\(")
_ASYNC_OPENAI_RE = re.compile(r"AsyncOpenAI\s*\(")


def _py_files():
    return [p for p in _APP.rglob("*.py") if "__pycache__" not in p.parts]


def test_no_direct_sdk_call_outside_allowlist():
    offenders = []
    for path in _py_files():
        rel = path.relative_to(_APP).as_posix()
        if rel in _SDK_ALLOWLIST:
            continue
        if _SDK_CALL_RE.search(path.read_text(encoding="utf-8")):
            offenders.append(rel)
    assert not offenders, (
        "Gọi OpenAI SDK TRỰC TIẾP ngoài allowlist -> BYPASS ai-router. "
        "Đưa lời gọi vào provider route-aware (embedding.py/rerank.py). "
        f"Vi phạm: {offenders}"
    )


def test_async_openai_clients_pass_base_url():
    """Mọi file tạo AsyncOpenAI PHẢI có base_url -> không khoá cứng api.openai.com."""
    not_route_aware = []
    for path in _py_files():
        text = path.read_text(encoding="utf-8")
        if _ASYNC_OPENAI_RE.search(text) and "base_url" not in text:
            not_route_aware.append(path.relative_to(_APP).as_posix())
    assert not not_route_aware, (
        "AsyncOpenAI KHÔNG truyền base_url -> bypass router + khoá OpenAI. "
        f"Vi phạm: {not_route_aware}"
    )
