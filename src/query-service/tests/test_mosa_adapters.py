"""Phase 1 — adapter reasoning + MosaChatModel.

Không gọi mạng: chỉ kiểm transform_params / parse_usage / build params của model.
Phản ánh đúng probe o3-mini: reasoning model BỎ temperature/top_p, THÊM reasoning_effort.
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage

from app.infrastructure.llm.registry import get_adapter
from app.infrastructure.llm.chat_model import MosaChatModel, build_node_chat_model


# ----------------------------------------------------------------- adapters pure
def test_reasoning_oai_strips_sampling_adds_effort():
    a = get_adapter("reasoning_oai")
    base = {"model": "o3-mini", "temperature": 0.0, "top_p": 0.9, "max_completion_tokens": 2000}
    out = a.transform_params(base, reasoning_effort="medium")
    assert "temperature" not in out
    assert "top_p" not in out
    assert out["reasoning_effort"] == "medium"
    assert out["max_completion_tokens"] == 2000
    assert base["temperature"] == 0.0  # không mutate input


def test_reasoning_oai_no_effort_when_none_or_invalid():
    a = get_adapter("reasoning_oai")
    assert "reasoning_effort" not in a.transform_params({"temperature": 0}, reasoning_effort=None)
    assert "reasoning_effort" not in a.transform_params({"temperature": 0}, reasoning_effort="bogus")


def test_reasoning_oai_drops_effort_when_tools_present():
    # chat.completions: tools + reasoning_effort -> OpenAI 400 (gpt-5.4-mini/o-series).
    a = get_adapter("reasoning_oai")
    with_tools = a.transform_params({"tools": [{"type": "function"}]}, reasoning_effort="medium")
    assert "reasoning_effort" not in with_tools
    no_tools = a.transform_params({}, reasoning_effort="medium")
    assert no_tools["reasoning_effort"] == "medium"


def test_openrouter_effort_puts_reasoning_in_extra_body():
    """Cắt độ nghĩ: reasoning_effort -> nested reasoning:{effort} trong extra_body (OpenRouter),
    KHÔNG top-level reasoning_effort; bỏ sampling param. Không mutate input."""
    a = get_adapter("openrouter_effort")
    base = {"model": "deepseek/deepseek-v4-flash", "temperature": 0.0, "top_p": 1,
            "max_completion_tokens": 3000}
    out = a.transform_params(base, reasoning_effort="low")
    assert "temperature" not in out and "top_p" not in out
    assert "reasoning_effort" not in out                       # không top-level
    assert out["extra_body"]["reasoning"] == {"effort": "low"}  # nested cho OpenRouter
    assert out["max_completion_tokens"] == 3000
    assert base["temperature"] == 0.0                          # input không bị mutate
    assert a.surfaces_reasoning_stream() is True


def test_openrouter_effort_no_reasoning_when_none_or_invalid():
    a = get_adapter("openrouter_effort")
    assert "extra_body" not in a.transform_params({"temperature": 0}, reasoning_effort=None)
    assert "extra_body" not in a.transform_params({"temperature": 0}, reasoning_effort="bogus")


def test_reasoning_or_strips_sampling_and_streams_reasoning():
    a = get_adapter("reasoning_or")
    out = a.transform_params({"temperature": 0.0, "top_p": 1, "reasoning_effort": "high"})
    assert "temperature" not in out
    assert "top_p" not in out
    assert "reasoning_effort" not in out          # deepseek không dùng effort
    assert a.surfaces_reasoning_stream() is True


def test_standard_does_not_surface_reasoning_stream():
    assert get_adapter("standard").surfaces_reasoning_stream() is False


# ------------------------------------------------------------- MosaChatModel params
def _msgs():
    return [HumanMessage(content="Chính sách nghỉ phép là gì?")]


def test_mosa_reasoning_model_build_params_no_temperature():
    m = MosaChatModel(api_key="x", model="o3-mini", adapter_name="reasoning_oai", reasoning_effort="medium")
    params = m._build_params(_msgs())
    assert "temperature" not in params
    assert params["reasoning_effort"] == "medium"
    assert "max_completion_tokens" in params
    assert params["model"] == "o3-mini"


def test_mosa_standard_model_keeps_temperature():
    m = MosaChatModel(api_key="x", model="gpt-4o-mini", adapter_name="standard")
    params = m._build_params(_msgs())
    assert "temperature" in params
    assert "reasoning_effort" not in params


def test_mosa_usage_metadata_delegates_to_adapter():
    m = MosaChatModel(api_key="x", model="o3-mini", adapter_name="reasoning_oai")
    usage = {
        "prompt_tokens": 27,
        "completion_tokens": 201,
        "total_tokens": 228,
        "completion_tokens_details": {"reasoning_tokens": 128},
    }
    um = m._usage_metadata(usage)
    assert um["input_tokens"] == 27
    assert um["output_token_details"]["reasoning"] == 128


def test_mosa_bind_tools_preserves_adapter_config():
    m = MosaChatModel(api_key="x", model="o3-mini", adapter_name="reasoning_oai", reasoning_effort="high")
    bound = m.bind_tools([], tool_choice="auto")
    assert isinstance(bound, MosaChatModel)
    assert bound.adapter_name == "reasoning_oai"
    assert bound.reasoning_effort == "high"
    # adapter vẫn áp đúng sau bind
    assert "temperature" not in bound._build_params(_msgs())


# ----------------------------------------------------------------- build factory
def test_build_node_model_routed_uses_capability():
    m = build_node_chat_model("think", api_key="x", base_url="http://ai-router:8010/v1")
    assert m.adapter_name == "standard"   # default an toàn (xem profiles.yaml)
    assert m.model == "think"             # routed -> field model = capability


def test_build_node_model_direct_uses_real_model():
    m = build_node_chat_model("think", api_key="x", base_url=None, direct_model="gpt-4o-mini")
    assert m.model == "gpt-4o-mini"       # direct -> direct_model khi profiles.models rỗng


def test_build_node_model_triage_is_fast_no_reasoning():
    m = build_node_chat_model("triage", api_key="x", base_url="http://ai-router:8010/v1")
    assert m.adapter_name == "openrouter_effort"   # tắt reasoning (off) -> classify nhanh
    assert m.model == "triage_fast"                # capability triage_fast = Qwen nhanh (OFF OpenAI)
