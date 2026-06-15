"""Test lõi router offline (MemoryCounters, không gọi mạng).

Chạy: python -m pytest tests/  HOẶC  python tests/test_router_core.py
Phủ: auto-discover key, provider-split tên model, sticky rotation + spill tier, pin embedding.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_router.catalog import Catalog
from ai_router.config import CapabilityConfig, RoutingTable, SelectorConfig
from ai_router.counters import MemoryCounters
from ai_router.registry import OPENROUTER_BASE_URL, TIER_DEFS, Registry, discover_keys
from ai_router.schemas import KeyEntry, Limit, ModelEntry, Provider
from ai_router.selector import ResolveRequest, build_selector


def _catalog() -> Catalog:
    return Catalog([
        ModelEntry(id="openai/gpt-4o-mini", provider="openai", name_native="gpt-4o-mini",
                   name_or="openai/gpt-4o-mini", context_length=128000, supports_tools=True,
                   is_free=False, endpoint="chat"),
        ModelEntry(id="qwen/qwen3:free", provider="qwen", name_native="qwen3",
                   name_or="qwen/qwen3:free", context_length=262144, supports_tools=True,
                   is_free=True, endpoint="chat"),
        ModelEntry(id="deepseek/deepseek-v4-flash", provider="deepseek", name_native="deepseek-v4-flash",
                   name_or="deepseek/deepseek-v4-flash", context_length=1000000, supports_tools=True,
                   is_free=False, price_out_with_fee=0.2, endpoint="chat"),
        ModelEntry(id="openai/text-embedding-3-small", provider="openai", name_native="text-embedding-3-small",
                   name_or="openai/text-embedding-3-small", context_length=8191, endpoint="embeddings"),
    ])


def _registry(oai_limit=100, or_req=2) -> Registry:
    keys = [
        KeyEntry(id="oai-1", provider=Provider.OPENAI, base_url=None, api_key_env="OPENAI_API_KEY_1",
                 tier="free_oai", limit=Limit(kind="tokens_per_day", value=oai_limit)),
        KeyEntry(id="or-1", provider=Provider.OPENROUTER, base_url=OPENROUTER_BASE_URL,
                 api_key_env="OPENROUTER_API_KEY_1", tier="free_or",
                 limit=Limit(kind="requests_per_day", value=or_req, rpm=20)),
    ]
    env = {"OPENAI_API_KEY_1": "sk-oai", "OPENROUTER_API_KEY_1": "sk-or"}
    return Registry(keys, env)


def _table() -> RoutingTable:
    return RoutingTable(
        version=1, selector=SelectorConfig(impl="sticky_rotation_soft"),
        capabilities={
            "answer": CapabilityConfig(
                tiers=["free_oai", "free_or", "paid"],
                models={"free_oai": "openai/gpt-4o-mini", "free_or": "qwen/qwen3:free",
                        "paid": "deepseek/deepseek-v4-flash"}),
            "embed": CapabilityConfig(tiers=["embed_oai"], pinned_model="openai/text-embedding-3-small"),
        },
    )


def _selector(counters, registry, catalog):
    return build_selector("sticky_rotation_soft", registry=registry, catalog=catalog,
                          counters=counters, tier_defs=TIER_DEFS, params={})


def test_discover_keys_excludes_legacy():
    env = {"OPENAI_API_KEY": "legacy", "OPENAI_API_KEY_1": "a", "OPENAI_API_KEY_2": "b",
           "OPENROUTER_API_KEY_1": "c", "RANDOM": "x"}
    keys = discover_keys(env)
    ids = sorted(k.id for k in keys)
    assert ids == ["oai-1", "oai-2", "or-1"], ids
    assert all(k.api_key_env != "OPENAI_API_KEY" for k in keys)
    print("OK discover_keys (loại key đơn legacy)")


def test_provider_split_and_first_choice():
    async def run():
        cat, reg, tbl = _catalog(), _registry(), _table()
        sel = _selector(MemoryCounters(), reg, cat)
        req = ResolveRequest(capability="answer", cap_config=tbl.capabilities["answer"],
                             est_tokens=10, has_tools=True)
        dec = await sel.resolve(req)
        assert dec is not None and dec.tier == "free_oai"
        assert dec.key_id == "oai-1"
        assert dec.model_name == "gpt-4o-mini"   # OpenAI = tên TRẦN (provider-split)
        print("OK first-choice free_oai + tên trần:", dec.public())
    asyncio.run(run())


def test_spill_through_tiers():
    async def run():
        cat, reg, tbl = _catalog(), _registry(oai_limit=30, or_req=2), _table()
        counters = MemoryCounters()
        sel = _selector(counters, reg, cat)
        cap = tbl.capabilities["answer"]

        def mkreq():
            return ResolveRequest(capability="answer", cap_config=cap, est_tokens=10, has_tools=True)

        tiers = []
        for _ in range(6):
            dec = await sel.resolve(mkreq())
            tiers.append((dec.tier, dec.key_id, dec.model_name) if dec else None)
        # oai limit 30 / est 10 -> 3 lần free_oai; or_req 2 -> 2 lần free_or; rồi paid
        assert tiers[0][0] == "free_oai" and tiers[2][0] == "free_oai"
        assert tiers[3][0] == "free_or" and tiers[3][2] == "qwen/qwen3:free"  # OpenRouter = có provider
        assert tiers[5][0] == "paid" and tiers[5][2] == "deepseek/deepseek-v4-flash"
        print("OK spill bậc thang:", [t[0] for t in tiers])
    asyncio.run(run())


def test_embed_pin():
    async def run():
        cat, reg, tbl = _catalog(), _registry(), _table()
        sel = _selector(MemoryCounters(), reg, cat)
        req = ResolveRequest(capability="embed", cap_config=tbl.capabilities["embed"],
                             est_tokens=0, endpoint="embeddings")
        dec = await sel.resolve(req)
        assert dec is not None and dec.model_id == "openai/text-embedding-3-small"
        assert dec.model_name == "text-embedding-3-small" and dec.tier == "embed_oai"
        print("OK embed PIN:", dec.public())
    asyncio.run(run())


if __name__ == "__main__":
    test_discover_keys_excludes_legacy()
    test_provider_split_and_first_choice()
    test_spill_through_tiers()
    test_embed_pin()
    print("\nALL TESTS PASSED")
