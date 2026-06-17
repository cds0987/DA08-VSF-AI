"""Test observability + robustness mới: classify 429, UsageReconciler, metric render.

Chạy: python -m pytest tests/test_router_observability.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_router.observability import Metrics, render_prometheus
from ai_router.reconcile import OpenRouterReconciler
from ai_router.registry import OPENROUTER_BASE_URL, Registry
from ai_router.router import classify_provider_error
from ai_router.schemas import KeyEntry, Limit, Provider


class _RateLimit(Exception):
    def __init__(self, msg, status_code=429):
        super().__init__(msg)
        self.status_code = status_code


def test_classify_quota_vs_rate_vs_model():
    assert classify_provider_error(_RateLimit("You exceeded your current quota")) == "quota"
    assert classify_provider_error(_RateLimit("insufficient_quota")) == "quota"
    assert classify_provider_error(_RateLimit("Rate limit reached for gpt-4o-mini")) == "rate"
    assert classify_provider_error(Exception("connection reset")) == "model"
    assert classify_provider_error(Exception("500 internal server error")) == "model"
    print("OK classify 429 quota/rate/model")


def test_reconciler_openrouter_stub():
    async def run():
        reg = Registry(
            [KeyEntry(id="or-1", provider=Provider.OPENROUTER, base_url=OPENROUTER_BASE_URL,
                      api_key_env="OPENROUTER_API_KEY_1", tier="free_or",
                      limit=Limit(kind="requests_per_day", value=1000))],
            {"OPENROUTER_API_KEY_1": "sk-or"},
        )

        async def stub_fetch(secret):
            assert secret == "sk-or"
            return {"usage": 1.5, "limit": 10.0}

        rows = await OpenRouterReconciler(fetch=stub_fetch).reconcile(reg)
        assert rows == [{"key_id": "or-1", "provider": "openrouter", "usage": 1.5, "limit": 10.0}]
        print("OK reconciler OpenRouter:", rows)
    asyncio.run(run())


def test_reconciler_swallows_fetch_error():
    async def run():
        reg = Registry(
            [KeyEntry(id="or-1", provider=Provider.OPENROUTER, base_url=OPENROUTER_BASE_URL,
                      api_key_env="OPENROUTER_API_KEY_1", tier="free_or")],
            {"OPENROUTER_API_KEY_1": "sk-or"},
        )

        async def boom(secret):
            raise RuntimeError("network down")

        rows = await OpenRouterReconciler(fetch=boom).reconcile(reg)
        assert rows == []  # lỗi nuốt, không sập
        print("OK reconciler best-effort")
    asyncio.run(run())


def test_metrics_render_new_counters():
    m = Metrics()
    labels = {"key_id": "oai-1", "secret_env": "OPENAI_API_KEY_1", "model": "openai/gpt-5.4-mini",
              "capability": "think", "tier": "free_oai", "provider": "openai"}
    m.inc("airouter_calls_total", {**labels, "status": "ok"})
    m.inc("airouter_tokens_total", labels, 1234.0)
    m.inc("airouter_cost_usd_total", labels, 0.0021)
    m.inc("airouter_band_rotation_total", {"scope": "think:free_oai", "tier": "free_oai"})
    text = render_prometheus({"keys": []}, m)
    for name in ("airouter_calls_total", "airouter_tokens_total", "airouter_cost_usd_total",
                 "airouter_band_rotation_total"):
        assert f"# TYPE {name} counter" in text, name
        assert name in text
    assert 'model="openai/gpt-5.4-mini"' in text
    print("OK metrics render per-key×model")


if __name__ == "__main__":
    test_classify_quota_vs_rate_vs_model()
    test_reconciler_openrouter_stub()
    test_reconciler_swallows_fetch_error()
    test_metrics_render_new_counters()
    print("\nALL TESTS PASSED")
