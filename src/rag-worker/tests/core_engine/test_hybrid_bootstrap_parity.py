"""Regression: VECTOR_HYBRID phải áp ĐỒNG NHẤT cho CẢ 2 nhánh bootstrap.

Bug đã cắn (e371bef): nhánh config.yaml dựng vector_config qua to_vector_store_config()
KHÔNG map hybrid -> mặc định False; chỉ nhánh from_env đọc VECTOR_HYBRID. Hậu quả: worker
(config.yaml, hybrid=False) upsert vector UNNAMED vào collection named dense+sparse (auto_migrate
tạo theo from_env hybrid=True) -> Qdrant 400 "Not existing vector name", ingest fail âm thầm.
e2e KHÔNG bắt được vì VECTOR_HYBRID off + không chạy auto_migrate. Test này chốt parity.
"""
from __future__ import annotations

import pytest

from app.interfaces.api.runtime import apply_hybrid_from_env, hybrid_enabled_from_env
from core_engine.config_schema import PipelineConfig
from core_engine.mapping import to_vector_store_config
from core_engine.vectorstore.config import VectorStoreConfig


def _cfg() -> PipelineConfig:
    return PipelineConfig.model_validate(
        {
            "common": {"ai_mode": "offline"},
            "embedder": {"model": "qwen/qwen3-embedding-4b", "dimension": 2560},
            "captioner": {"impl": "none", "model": "gpt-4o-mini", "params": {}},
            "parser": {"impl": "local", "params": {"max_workers": 2}},
            "chunker": {"impl": "heading_sections", "params": {}},
            "vector_store": {"impl": "qdrant", "params": {"collection": "rag_chatbot"}},
        }
    )


def test_to_vector_store_config_omits_hybrid() -> None:
    """Nhánh config.yaml KHÔNG mang hybrid (gap) -> bootstrap PHẢI override từ env."""
    vc = to_vector_store_config(_cfg(), dim=2560)
    assert vc.hybrid is False


@pytest.mark.parametrize("val,expected", [("true", True), ("1", True), ("on", True),
                                          ("false", False), ("", False)])
def test_hybrid_enabled_from_env(monkeypatch, val, expected) -> None:
    monkeypatch.setenv("VECTOR_HYBRID", val)
    assert hybrid_enabled_from_env() is expected


def test_apply_hybrid_overrides_config_yaml_branch(monkeypatch) -> None:
    monkeypatch.setenv("VECTOR_HYBRID", "true")
    vc = to_vector_store_config(_cfg(), dim=2560)   # hybrid=False (gap)
    assert apply_hybrid_from_env(vc).hybrid is True


def test_two_branch_parity(monkeypatch) -> None:
    """from_env (env-branch) và config.yaml-branch + override -> CÙNG hybrid."""
    monkeypatch.setenv("VECTOR_HYBRID", "true")
    env_branch = VectorStoreConfig.from_env(model="qwen/qwen3-embedding-4b", dimension=2560)
    yaml_branch = apply_hybrid_from_env(to_vector_store_config(_cfg(), dim=2560))
    assert env_branch.hybrid is True
    assert yaml_branch.hybrid == env_branch.hybrid

    monkeypatch.setenv("VECTOR_HYBRID", "false")
    env_off = VectorStoreConfig.from_env(model="qwen/qwen3-embedding-4b", dimension=2560)
    yaml_off = apply_hybrid_from_env(to_vector_store_config(_cfg(), dim=2560))
    assert env_off.hybrid is False
    assert yaml_off.hybrid == env_off.hybrid
