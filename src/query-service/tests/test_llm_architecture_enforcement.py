"""GATE KIẾN TRÚC LLM — ép mọi dev sau tuân thủ tuyệt đối. Vi phạm = CI đỏ = KHÔNG lên prod.

Bối cảnh: query-service phải gọi LLM/embedding QUA adapter/client tập trung (có `base_url`)
để đi qua ai-router (cân bằng key, cost-per-key, fallback). Nếu dev mới gọi thẳng OpenAI SDK
ở node/use-case -> BYPASS router -> mất cân bằng + observability + khoá cứng OpenAI. 3 gate:

  GATE 1: SDK LLM call (responses/chat.completions/embeddings .create) CHỈ được ở allowlist
          adapter/client. File khác gọi -> FAIL (buộc đi qua lớp trừu tượng route được).
  GATE 2: Capability gửi cho router (llm/intent/guardrail) PHẢI tồn tại trong routing.yaml
          -> chống typo gây 404 NoCapacity ở prod. + chống drift capability set.
  GATE 3: Mọi BaseChatModel adapter PHẢI giữ surface graph/orchestration cần.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1] / "app"

# Chỉ các file SAU được phép gọi OpenAI SDK trực tiếp (lớp adapter/client route-aware).
# Thêm file vào đây = quyết định kiến trúc CÓ Ý THỨC (phải đảm bảo file đó đọc openai_base_url).
_SDK_CALL_ALLOWLIST = {
    "infrastructure/external/langchain_chat_adapter.py",        # chat.completions (chuẩn, route)
    "infrastructure/external/openai_client.py",                 # legacy streaming client
    "infrastructure/external/intent_ai_client.py",              # intent embed + LLM
    "infrastructure/external/tool_decision_client.py",          # deprecated
    "infrastructure/guardrails/llm_guard_service.py",           # guardrail judge
}

_SDK_CALL_RE = re.compile(r"\.(responses|chat\.completions|embeddings)\.create\s*\(")

# Capability hợp lệ = capabilities trong ai-router/routing.yaml. Hardcode làm HỢP ĐỒNG (chạy
# được cả khi build query-service biệt lập); nếu thấy routing.yaml thì cross-check chống drift.
# plan + synth = capability RIÊNG per-step MOSA (orchestrate=plan, think2=synth) -> đổi model
# chỉ sửa routing.yaml, không sửa code.
_EXPECTED_CAPABILITIES = {"answer", "triage", "think", "worker", "rerank", "guardrail", "summary",
                          "caption", "ocr", "embed", "plan", "synth", "rerank_api"}


def _py_files():
    return [p for p in _APP.rglob("*.py") if "__pycache__" not in p.parts]


# ----------------------------------------------------------------- GATE 1
def test_no_direct_openai_sdk_call_outside_allowlist():
    offenders: list[str] = []
    for path in _py_files():
        rel = path.relative_to(_APP).as_posix()
        if rel in _SDK_CALL_ALLOWLIST:
            continue
        text = path.read_text(encoding="utf-8")
        if _SDK_CALL_RE.search(text):
            offenders.append(rel)
    assert not offenders, (
        "Gọi OpenAI SDK TRỰC TIẾP ngoài allowlist -> BYPASS ai-router. "
        "Đưa lời gọi vào adapter/client route-aware (đọc openai_base_url) thay vì gọi thẳng. "
        f"Vi phạm: {offenders}"
    )


# --------------------------------------------------------------- GATE 1b
# File route-aware PHẢI thực sự đọc base_url (qua build_routed_openai hoặc trực tiếp). Chặn
# tái diễn bug: client tạo AsyncOpenAI() KHÔNG base_url -> SDK âm thầm đọc env OPENAI_BASE_URL
# -> responses.create bắn /v1/responses (router không có) -> 404 -> guardrail fail-open câm.
# langchain_responses_adapter = kill-switch legacy CỐ Ý không route -> loại trừ.
_ROUTE_AWARE_REQUIRED = _SDK_CALL_ALLOWLIST - {
    "infrastructure/external/langchain_responses_adapter.py",
}


def test_allowlisted_clients_are_route_aware():
    not_route_aware: list[str] = []
    for rel in sorted(_ROUTE_AWARE_REQUIRED):
        text = (_APP / rel).read_text(encoding="utf-8")
        if "build_routed_openai" not in text and "base_url" not in text:
            not_route_aware.append(rel)
    assert not not_route_aware, (
        "File trong allowlist gọi SDK nhưng KHÔNG route-aware (thiếu build_routed_openai/base_url) "
        "-> nguy cơ bypass router + bug âm thầm /v1/responses 404. "
        f"Vi phạm: {not_route_aware}"
    )


# ----------------------------------------------------------------- GATE 2
def test_capability_settings_are_valid():
    from app.infrastructure.config import Settings

    s = Settings()
    for field in ("llm_capability", "intent_capability", "guardrail_capability", "summary_capability"):
        cap = getattr(s, field)
        assert cap in _EXPECTED_CAPABILITIES, (
            f"{field}={cap!r} KHÔNG phải capability hợp lệ -> router trả unknown_capability (404). "
            f"Hợp lệ: {sorted(_EXPECTED_CAPABILITIES)}"
        )


def test_capability_set_matches_routing_yaml_no_drift():
    """Nếu thấy ai-router/routing.yaml -> hợp đồng _EXPECTED_CAPABILITIES không được lệch."""
    routing = Path(__file__).resolve().parents[2] / "ai-router" / "routing.yaml"
    if not routing.exists():
        pytest.skip("routing.yaml không có trong context build này (query-service biệt lập)")
    import yaml

    data = yaml.safe_load(routing.read_text(encoding="utf-8")) or {}
    actual = set((data.get("capabilities") or {}).keys())
    assert actual == _EXPECTED_CAPABILITIES, (
        "Capability set lệch giữa routing.yaml và hợp đồng test. Cập nhật _EXPECTED_CAPABILITIES "
        f"khi đổi routing.yaml. routing.yaml={sorted(actual)} contract={sorted(_EXPECTED_CAPABILITIES)}"
    )


# ----------------------------------------------------------------- GATE 3
@pytest.mark.parametrize("dotted", [
    "app.infrastructure.external.langchain_chat_adapter.OpenAIChatModel",
])
def test_adapter_preserves_basechatmodel_surface(dotted):
    import importlib

    mod_name, cls_name = dotted.rsplit(".", 1)
    cls = getattr(importlib.import_module(mod_name), cls_name)
    # Surface graph/orchestration phụ thuộc — adapter mới PHẢI có đủ.
    for attr in ("bind_tools", "with_structured_output", "_astream", "_should_stream",
                 "_agenerate", "invoke"):
        assert callable(getattr(cls, attr, None)), f"{cls_name} thiếu {attr}() -> phá hợp đồng LangGraph"
