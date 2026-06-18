"""Test WS-A canonical model: catalog.canonicalize + cost chịu id dated + router ghi đè model.

Chạy: python -m pytest tests/test_catalog.py -q  HOẶC  python tests/test_catalog.py
Phủ: strip-date (không fuzzy), exact/date_strip/unmatched, cost(dated)==cost(canonical),
     Router._canon_model ghi đè model về dec.model_id + phát drift khi model lạ.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_router.catalog import Catalog
from ai_router.observability import Metrics
from ai_router.router import Router
from ai_router.schemas import ModelEntry


def _catalog() -> Catalog:
    return Catalog([
        ModelEntry(id="openai/gpt-5.4-mini", provider="openai", name_native="gpt-5.4-mini",
                   name_or="openai/gpt-5.4-mini", context_length=128000,
                   price_in_with_fee=0.15, price_out_with_fee=0.6, endpoint="chat"),
        ModelEntry(id="deepseek/deepseek-v4-flash", provider="deepseek",
                   name_native="deepseek-v4-flash", name_or="deepseek/deepseek-v4-flash",
                   context_length=1000000, endpoint="chat"),
    ])


def test_canonicalize_exact():
    cat = _catalog()
    assert cat.canonicalize("openai/gpt-5.4-mini") == ("openai/gpt-5.4-mini", "exact")
    # native name cũng exact -> trả id canonical
    assert cat.canonicalize("gpt-5.4-mini") == ("openai/gpt-5.4-mini", "exact")
    print("OK canonicalize exact")


def test_canonicalize_date_strip():
    cat = _catalog()
    # đuôi -YYYY-MM-DD
    assert cat.canonicalize("gpt-5.4-mini-2026-03-17") == ("openai/gpt-5.4-mini", "date_strip")
    # đuôi -YYYYMMDD trên id có provider
    assert cat.canonicalize("deepseek/deepseek-v4-flash-20260423") == (
        "deepseek/deepseek-v4-flash", "date_strip")
    print("OK canonicalize date_strip")


def test_canonicalize_unmatched():
    cat = _catalog()
    # không trong catalog, không có date -> giữ nguyên, unmatched
    assert cat.canonicalize("acme/mystery-model") == ("acme/mystery-model", "unmatched")
    # có date nhưng strip xong vẫn không khớp -> trả bản đã strip, unmatched
    assert cat.canonicalize("acme/mystery-2026-01-01") == ("acme/mystery", "unmatched")
    print("OK canonicalize unmatched (no fuzzy)")


def test_cost_dated_equals_canonical():
    cat = _catalog()
    canonical = cat.cost("openai/gpt-5.4-mini", 1000, 2000)
    dated = cat.cost("gpt-5.4-mini-2026-03-17", 1000, 2000)
    assert canonical is not None and canonical > 0
    assert dated == canonical, (dated, canonical)
    print("OK cost(dated) == cost(canonical):", canonical)


def test_canon_model_overwrites_and_keeps_served():
    cat, m = _catalog(), Metrics()
    stub = SimpleNamespace(catalog=cat, metrics=m)
    dec = SimpleNamespace(model_id="openai/gpt-5.4-mini")
    data = {"model": "gpt-5.4-mini-2026-03-17", "choices": []}
    Router._canon_model(stub, data, dec, "think")
    assert data["model"] == "openai/gpt-5.4-mini"          # GOM canonical
    # model khớp catalog (date_strip) -> KHÔNG drift
    assert not any(name == "airouter_model_unmatched_total" for name, _, _ in m.snapshot())
    print("OK _canon_model ghi đè model về canonical")


def test_canon_model_emits_drift_on_unknown():
    cat, m = _catalog(), Metrics()
    stub = SimpleNamespace(catalog=cat, metrics=m)
    dec = SimpleNamespace(model_id="openai/gpt-5.4-mini")
    data = {"model": "acme/mystery-model"}
    Router._canon_model(stub, data, dec, "think")
    drift = [(lbls, v) for name, lbls, v in m.snapshot() if name == "airouter_model_unmatched_total"]
    assert drift and drift[0][0]["model"] == "acme/mystery-model"
    assert data["model"] == "openai/gpt-5.4-mini"
    print("OK _canon_model phát drift khi model lạ:", drift)


if __name__ == "__main__":
    test_canonicalize_exact()
    test_canonicalize_date_strip()
    test_canonicalize_unmatched()
    test_cost_dated_equals_canonical()
    test_canon_model_overwrites_and_keeps_served()
    test_canon_model_emits_drift_on_unknown()
    print("\nALL TESTS PASSED")
