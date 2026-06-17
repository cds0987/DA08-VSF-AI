"""Smoke test: gateway BOOT được + /health + /v1/route resolve (offline, KHÔNG gọi provider).

Bắt lỗi "app không khởi động" / "resolve vỡ" trước khi build image. /v1/route chỉ chọn
(key, model) từ Redis/counter — không forward lên OpenAI/OpenRouter nên chạy được trong CI.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Phải set TRƯỚC khi import app.main (Router đọc env lúc khởi tạo, auto-discover key).
os.environ.setdefault("OPENAI_API_KEY_1", "sk-test-oai")
os.environ.setdefault("OPENROUTER_API_KEY_1", "sk-test-or")
os.environ.pop("AIROUTER_REDIS_URL", None)        # ép MemoryCounters (không cần Redis trong CI)
os.environ.pop("AIROUTER_INTERNAL_TOKEN", None)   # bỏ auth để smoke /v1/route

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["keys"] >= 2          # 2 key giả vừa set
    assert body["models"] > 0         # catalog nạp được


def test_route_resolves_answer():
    r = client.post("/v1/route", json={
        "capability": "answer",
        "messages": [{"role": "user", "content": "chính sách nghỉ phép thế nào?"}],
    })
    assert r.status_code == 200, r.text
    dec = r.json()
    assert dec["model_name"] and dec["tier"]
    assert dec["provider"] in ("openai", "openrouter")


def test_metrics_exposes_per_key_and_counters():
    # resolve vài lần để sinh counter resolve_total -> đảm bảo /metrics có series.
    for _ in range(2):
        client.post("/v1/route", json={"capability": "answer",
                                       "messages": [{"role": "user", "content": "x"}]})
    r = client.get("/metrics")
    assert r.status_code == 200, r.text
    body = r.text
    # per-key gauge + secret_env (định danh GitHub secret, KHÔNG raw key)
    assert "airouter_key_remaining{" in body or "airouter_key_tokens_today{" in body
    assert 'secret_env="OPENAI_API_KEY_1"' in body
    assert "sk-test-oai" not in body          # KHÔNG bao giờ lộ raw key
    # leading indicator
    assert "airouter_resolve_total{" in body
    assert "airouter_keys_total " in body
