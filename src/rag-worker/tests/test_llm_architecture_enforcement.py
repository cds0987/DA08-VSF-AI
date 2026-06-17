"""GATE KIẾN TRÚC LLM (rag-worker) — ép mọi call AI (embed/caption/OCR ingestion) đi qua
lớp provider route-aware (có base_url) để KHỐNG CHẾ HẾT (observability-plan §11.1).

Bối cảnh: rag-worker embed mỗi chunk + caption/OCR ảnh. Nếu dev mới tạo AsyncOpenAI()
KHÔNG base_url -> khoá cứng OpenAI, BYPASS ai-router (mất cân bằng key + cost + observ).

  GATE 1 : SDK call CHỈ ở OpenAIProvider (điểm vào SDK duy nhất).
  GATE 1b: file tạo AsyncOpenAI PHẢI truyền base_url.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
# Quét code runtime: core_engine (pipeline AI) + app. Loại tests/migrations/scripts (dev tooling).
_SCAN_DIRS = [_ROOT / "core_engine", _ROOT / "app"]

# Điểm vào SDK duy nhất (nhận base_url qua CapabilityConfig -> trỏ ai-router được).
_SDK_ALLOWLIST = {"core_engine/ai/openai_provider.py"}

_SDK_CALL_RE = re.compile(r"\.(responses|chat\.completions|embeddings)\.create\s*\(")
_ASYNC_OPENAI_RE = re.compile(r"AsyncOpenAI\s*\(")


def _py_files():
    out = []
    for d in _SCAN_DIRS:
        if d.exists():
            out += [p for p in d.rglob("*.py")
                    if "__pycache__" not in p.parts and "tests" not in p.parts]
    return out


def test_no_direct_sdk_call_outside_allowlist():
    offenders = []
    for path in _py_files():
        rel = path.relative_to(_ROOT).as_posix()
        if rel in _SDK_ALLOWLIST:
            continue
        if _SDK_CALL_RE.search(path.read_text(encoding="utf-8")):
            offenders.append(rel)
    assert not offenders, (
        "Gọi OpenAI SDK TRỰC TIẾP ngoài OpenAIProvider -> BYPASS ai-router. "
        f"Vi phạm: {offenders}"
    )


def test_async_openai_clients_pass_base_url():
    not_route_aware = []
    for path in _py_files():
        text = path.read_text(encoding="utf-8")
        if _ASYNC_OPENAI_RE.search(text) and "base_url" not in text:
            not_route_aware.append(path.relative_to(_ROOT).as_posix())
    assert not not_route_aware, (
        "AsyncOpenAI KHÔNG truyền base_url -> bypass router + khoá OpenAI. "
        f"Vi phạm: {not_route_aware}"
    )
