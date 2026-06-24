"""Test selector adaptive_balanced — 2 cơ chế theo loại key (offline, MemoryCounters):

- OpenAI tier  : TPM-headroom — rải đều theo token/phút, mỗi key ≤ tpm_per_key.
- OpenRouter   : AIMD — gate theo limit tự-dò (inflight < limit); grow/shrink đổi sức.

Chạy: python -m pytest tests/test_adaptive_balanced.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_router.catalog import Catalog
from ai_router.config import CapabilityConfig
from ai_router.counters import AIMD_INIT, MemoryCounters
from ai_router.registry import OPENROUTER_BASE_URL, TIER_DEFS, Registry
from ai_router.schemas import KeyEntry, Limit, ModelEntry, Provider
from ai_router.selector import ResolveRequest, build_selector


def _catalog() -> Catalog:
    return Catalog([
        ModelEntry(id="openai/gpt-4o-mini", provider="openai", name_native="gpt-4o-mini",
                   name_or="openai/gpt-4o-mini", context_length=128000, supports_tools=True,
                   is_free=False, endpoint="chat"),
        ModelEntry(id="deepseek/deepseek-v4-flash", provider="deepseek", name_native="deepseek-v4-flash",
                   name_or="deepseek/deepseek-v4-flash", context_length=1000000, supports_tools=True,
                   is_free=False, price_out_with_fee=0.2, endpoint="chat"),
        ModelEntry(id="xiaomi/mimo-v2.5", provider="xiaomi", name_native="mimo-v2.5",
                   name_or="xiaomi/mimo-v2.5", context_length=1000000, supports_tools=True,
                   is_free=False, price_out_with_fee=0.28, endpoint="chat"),
    ])


def _oai_registry(n=2) -> Registry:
    keys, env = [], {}
    for i in range(1, n + 1):
        keys.append(KeyEntry(id=f"oai-{i}", provider=Provider.OPENAI, base_url=None,
                             api_key_env=f"OPENAI_API_KEY_{i}", tier="free_oai",
                             limit=Limit(kind="tokens_per_day", value=10_000_000)))
        env[f"OPENAI_API_KEY_{i}"] = f"sk-{i}"
    return Registry(keys, env)


def _or_registry(n=2) -> Registry:
    keys, env = [], {}
    for i in range(1, n + 1):
        keys.append(KeyEntry(id=f"or-{i}", provider=Provider.OPENROUTER, base_url=OPENROUTER_BASE_URL,
                             api_key_env=f"OPENROUTER_API_KEY_{i}", tier="paid",
                             limit=Limit(kind="none", value=0, rpm=200)))
        env[f"OPENROUTER_API_KEY_{i}"] = f"sk-or-{i}"
    return Registry(keys, env)


def _sel(reg, params):
    return build_selector("adaptive_balanced", registry=reg, catalog=_catalog(),
                          counters=params.pop("_c"), tier_defs=TIER_DEFS, params=params)


def test_openai_spreads_by_tpm():
    """tpm_per_key=100, est=40 -> mỗi key nhận 2 (40,80) rồi cạn; 2 key = 4, req#5 = None."""
    async def run():
        c = MemoryCounters()
        cap = CapabilityConfig(tiers=["free_oai"], models={"free_oai": "openai/gpt-4o-mini"})
        sel = _sel(_oai_registry(2), {"_c": c, "tpm_per_key": 100})
        got = []
        for _ in range(4):
            d = await sel.resolve(ResolveRequest(capability="worker", cap_config=cap, est_tokens=40))
            assert d is not None
            got.append(d.key_id)
        dist = Counter(got)
        assert dist["oai-1"] == 2 and dist["oai-2"] == 2, dist          # rải đều theo TPM
        nxt = await sel.resolve(ResolveRequest(capability="worker", cap_config=cap, est_tokens=40))
        assert nxt is None, "vượt TPM mọi key -> phải None (save_mode off)"
        print("OK OpenAI TPM spread:", dict(dist))
    asyncio.run(run())


def test_openrouter_aimd_gates_and_adapts():
    """AIMD init=8: GIỮ inflight -> mỗi key tới 8 thì cạn; 2 key=16, req#17=None.
    aimd_grow nới -> nhận thêm; aimd_shrink co lại."""
    async def run():
        c = MemoryCounters()
        cap = CapabilityConfig(tiers=["paid"], models={"paid": "deepseek/deepseek-v4-flash"})
        sel = _sel(_or_registry(2), {"_c": c})
        held = []
        for _ in range(int(AIMD_INIT) * 2):                 # 16
            d = await sel.resolve(ResolveRequest(capability="plan", cap_config=cap, est_tokens=50))
            assert d is not None and d.inflight_token, "OR phải giữ slot in-flight"
            held.append(d)
        dist = Counter(d.key_id for d in held)
        assert dist["or-1"] == 8 and dist["or-2"] == 8, dist            # AIMD limit 8/key
        assert (await sel.resolve(ResolveRequest(capability="plan", cap_config=cap, est_tokens=50))) is None

        # AIMD grow: nới or-1 lên 9 -> nhận thêm 1 trên or-1
        await c.aimd_grow("or-1")
        assert await c.get_aimd_limit("or-1") == AIMD_INIT + 1
        d = await sel.resolve(ResolveRequest(capability="plan", cap_config=cap, est_tokens=50))
        assert d is not None and d.key_id == "or-1", "grow xong phải nhận thêm trên or-1"

        # AIMD shrink (429): co or-2 ×0.5
        await c.aimd_shrink("or-2")
        assert await c.get_aimd_limit("or-2") == AIMD_INIT * 0.5
        print("OK OpenRouter AIMD gate+adapt:", dict(dist),
              "or-1->", await c.get_aimd_limit("or-1"), "or-2->", await c.get_aimd_limit("or-2"))
    asyncio.run(run())


def test_model_split_round_robin():
    """models.paid = [deepseek, xiaomi] -> CHIA TẢI round-robin ~50/50 (không failover-first)."""
    async def run():
        c = MemoryCounters()
        cap = CapabilityConfig(tiers=["paid"],
                               models={"paid": ["deepseek/deepseek-v4-flash", "xiaomi/mimo-v2.5"]})
        sel = _sel(_or_registry(2), {"_c": c})
        seen = Counter()
        for _ in range(20):
            d = await sel.resolve(ResolveRequest(capability="answer", cap_config=cap, est_tokens=50))
            assert d is not None
            await c.release_inflight(d.key_id, d.inflight_token)  # giải phóng để không cạn AIMD
            seen[d.model_id] += 1
        assert seen["deepseek/deepseek-v4-flash"] == 10 and seen["xiaomi/mimo-v2.5"] == 10, seen
        print("OK model split RR:", dict(seen))
    asyncio.run(run())


if __name__ == "__main__":
    test_openai_spreads_by_tpm()
    test_openrouter_aimd_gates_and_adapts()
    test_model_split_round_robin()
    print("\nALL ADAPTIVE TESTS PASSED")
