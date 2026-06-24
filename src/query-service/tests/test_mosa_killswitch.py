"""Phase 4 — kill-switch: manifest/adapter lỗi KHÔNG làm vỡ node (fallback standard)."""
from __future__ import annotations

from langchain_core.messages import HumanMessage

from app.infrastructure.llm.chat_model import MosaChatModel, build_node_chat_model
from app.infrastructure.llm.loader import get_node_profile, FALLBACK_ADAPTER


def test_mosa_unregistered_adapter_falls_back_to_standard():
    m = MosaChatModel(api_key="x", model="o3-mini", adapter_name="adapter-khong-ton-tai")
    # adapter property fallback standard -> không raise
    assert m.adapter.name == "standard"
    # _build_params chạy được (standard giữ temperature, không reasoning_effort)
    params = m._build_params([HumanMessage(content="hi")])
    assert "temperature" in params


def test_build_node_model_bad_profiles_path_uses_standard():
    # profiles path lỗi -> get_node_profile fallback standard, capability = tên node
    prof = get_node_profile("think", path="/khong/co/profiles.yaml")
    assert prof.adapter == FALLBACK_ADAPTER
    assert prof.capability == "think"


def test_build_node_model_still_builds_with_bad_profiles(monkeypatch):
    # Dù manifest hỏng, build_node_chat_model vẫn dựng được model chạy được.
    m = build_node_chat_model("answer", api_key="x", base_url="http://r/v1")
    assert isinstance(m, MosaChatModel)
    assert m.adapter.name in {"standard", "reasoning_oai", "reasoning_or", "openrouter_effort"}
