"""Phase 0 — khung MOSA adapter: registry + profiles loader + base usage parse.

Không gọi mạng: chỉ kiểm registry, manifest, và logic params/usage thuần.
"""
from __future__ import annotations

import pytest

from app.infrastructure.llm.base import NodeLLMAdapter
from app.infrastructure.llm.registry import (
    available,
    get_adapter,
    is_registered,
    register,
)
from app.infrastructure.llm.loader import (
    FALLBACK_ADAPTER,
    NodeProfile,
    get_node_profile,
    load_profiles,
)


# --------------------------------------------------------------------- registry
def test_standard_adapter_registered():
    assert is_registered("standard")
    assert "standard" in available()
    assert isinstance(get_adapter("standard"), NodeLLMAdapter)


def test_get_unknown_adapter_raises():
    with pytest.raises(KeyError):
        get_adapter("khong-ton-tai")


def test_register_and_resolve_custom_adapter():
    @register("dummy_test_adapter")
    class _Dummy(NodeLLMAdapter):
        def transform_params(self, params, *, reasoning_effort=None):
            return dict(params)

    assert is_registered("dummy_test_adapter")
    inst = get_adapter("DUMMY_TEST_ADAPTER")  # case-insensitive
    assert isinstance(inst, _Dummy)
    assert inst.name == "dummy_test_adapter"


def test_register_duplicate_name_conflicts():
    @register("dup_adapter")
    class _A(NodeLLMAdapter):
        def transform_params(self, params, *, reasoning_effort=None):
            return params

    with pytest.raises(ValueError):
        @register("dup_adapter")
        class _B(NodeLLMAdapter):
            def transform_params(self, params, *, reasoning_effort=None):
                return params


# ---------------------------------------------------------------- standard params
def test_standard_keeps_temperature_drops_reasoning_effort():
    adapter = get_adapter("standard")
    base = {"model": "gpt-4o-mini", "temperature": 0.0, "reasoning_effort": "low"}
    out = adapter.transform_params(base, reasoning_effort="low")
    assert out["temperature"] == 0.0          # model thường giữ temperature
    assert "reasoning_effort" not in out       # nhưng không gửi reasoning_effort
    assert base["reasoning_effort"] == "low"   # KHÔNG mutate input


# ------------------------------------------------------------------- base usage
def test_base_usage_extracts_reasoning_tokens():
    adapter = get_adapter("standard")
    usage = {
        "prompt_tokens": 27,
        "completion_tokens": 201,
        "total_tokens": 228,
        "prompt_tokens_details": {"cached_tokens": 5},
        "completion_tokens_details": {"reasoning_tokens": 128},
    }
    parsed = adapter.parse_usage(usage)
    assert parsed["input_tokens"] == 27
    assert parsed["output_tokens"] == 201
    assert parsed["total_tokens"] == 228
    assert parsed["input_token_details"]["cache_read"] == 5
    assert parsed["output_token_details"]["reasoning"] == 128


def test_base_usage_none_and_no_details():
    adapter = get_adapter("standard")
    assert adapter.parse_usage(None) is None
    minimal = adapter.parse_usage({"prompt_tokens": 10, "completion_tokens": 3})
    assert minimal["output_token_details"]["reasoning"] == 0
    assert minimal["total_tokens"] == 13


# ----------------------------------------------------------------------- loader
def test_profiles_yaml_loads_expected_nodes():
    profiles = load_profiles()
    assert {"triage", "think", "answer"} <= set(profiles)


def test_think_node_profile_default_standard():
    # Mặc định an toàn: think=standard (chat.completions + tools KHÔNG dùng reasoning_effort).
    prof = get_node_profile("think")
    assert isinstance(prof, NodeProfile)
    assert prof.capability == "think"
    assert prof.adapter == "standard"
    assert prof.make_adapter().name == "standard"


def test_triage_node_profile():
    prof = get_node_profile("triage")
    assert prof.adapter == "standard"
    # capability = think (gpt-5.4-mini) để tránh regression phân loại của model rẻ.
    assert prof.capability == "think"
    assert prof.make_adapter().name == "standard"


def test_unknown_node_falls_back_to_standard():
    prof = get_node_profile("khong-co-node-nay")
    assert prof.adapter == FALLBACK_ADAPTER
    assert prof.capability == "khong-co-node-nay"
    assert prof.make_adapter().name == "standard"


def test_plan_node_profile():
    # plan = standard (KHÔNG cắt reasoning — để model nghĩ + stream; hiển thị xử lý ở FE).
    prof = get_node_profile("plan")
    assert prof.adapter == "standard"
    assert prof.capability == "plan"
    assert prof.reasoning_effort is None


def test_per_node_max_output_tokens():
    # think (planner) nâng trần để reasoning + JSON đủ chỗ -> hết retry; node không khai -> None
    # (build_node_chat_model dùng trần chung). answer nâng để câu trả lời không cụt.
    assert get_node_profile("think").max_output_tokens == 3000
    assert get_node_profile("answer").max_output_tokens == 4000  # node gộp verify_answer: nghĩ + viết
    assert get_node_profile("triage").max_output_tokens is None  # giữ trần chung 1500
    assert get_node_profile("khong-co-node-nay").max_output_tokens is None


def test_build_node_chat_model_uses_profile_max_output():
    from app.infrastructure.llm.chat_model import build_node_chat_model
    # think có trần 3000 trong profiles -> override trần chung 1500 truyền vào.
    m = build_node_chat_model("think", api_key="k", base_url="http://r/v1", max_output_tokens=1500)
    assert m.max_output_tokens == 3000
    # node không khai -> giữ trần chung truyền vào.
    m2 = build_node_chat_model("triage", api_key="k", base_url="http://r/v1", max_output_tokens=1500)
    assert m2.max_output_tokens == 1500


def test_make_adapter_unregistered_falls_back():
    # NodeProfile trỏ adapter chưa đăng ký -> make_adapter lùi về standard, không raise.
    prof = NodeProfile(node="x", adapter="adapter-ma", capability="x")
    assert prof.make_adapter().name == "standard"
