"""Test selector banded_rotation + weighted_banded + save mode (offline, MemoryCounters).

Phủ:
- banded_rotation: dính key tới khi đủ band -> xoay key kế (rải tải 250K).
- save mode: MỌI tier cạn -> ép gpt-4o-mini (OpenAI), bỏ trần free (vẫn band).
- reserve hard cap vẫn chặn (band không phá 2.5M).
- weighted_banded: tỉ lệ lane ~4:1 (gpt:deepseek) qua weighted round-robin.

Chạy: python -m pytest tests/test_banded_rotation.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_router.catalog import Catalog
from ai_router.config import CapabilityConfig, SelectorConfig
from ai_router.counters import MemoryCounters
from ai_router.registry import OPENROUTER_BASE_URL, TIER_DEFS, Registry
from ai_router.schemas import KeyEntry, Limit, ModelEntry, Provider
from ai_router.selector import ResolveRequest, build_selector


def _catalog() -> Catalog:
    return Catalog([
        ModelEntry(id="openai/gpt-5.4-mini", provider="openai", name_native="gpt-5.4-mini",
                   name_or="openai/gpt-5.4-mini", context_length=400000, supports_tools=True,
                   is_free=False, endpoint="chat"),
        ModelEntry(id="openai/gpt-4o-mini", provider="openai", name_native="gpt-4o-mini",
                   name_or="openai/gpt-4o-mini", context_length=128000, supports_tools=True,
                   is_free=False, endpoint="chat"),
        ModelEntry(id="deepseek/deepseek-v4-flash", provider="deepseek", name_native="deepseek-v4-flash",
                   name_or="deepseek/deepseek-v4-flash", context_length=1000000, supports_tools=True,
                   is_free=False, price_out_with_fee=0.2, endpoint="chat"),
    ])


def _registry(*, oai=2, openr=1, oai_limit=2_500_000) -> Registry:
    keys: list[KeyEntry] = []
    env: dict[str, str] = {}
    for i in range(1, oai + 1):
        keys.append(KeyEntry(id=f"oai-{i}", provider=Provider.OPENAI, base_url=None,
                             api_key_env=f"OPENAI_API_KEY_{i}", tier="free_oai",
                             limit=Limit(kind="tokens_per_day", value=oai_limit)))
        env[f"OPENAI_API_KEY_{i}"] = f"sk-oai-{i}"
    for i in range(1, openr + 1):
        keys.append(KeyEntry(id=f"or-{i}", provider=Provider.OPENROUTER, base_url=OPENROUTER_BASE_URL,
                             api_key_env=f"OPENROUTER_API_KEY_{i}", tier="free_or",
                             limit=Limit(kind="requests_per_day", value=100000, rpm=200)))
        env[f"OPENROUTER_API_KEY_{i}"] = f"sk-or-{i}"
    return Registry(keys, env)


def _sel(impl, params, counters, reg, cat):
    return build_selector(impl, registry=reg, catalog=cat, counters=counters,
                          tier_defs=TIER_DEFS, params=params)


# --------------------------------------------------------------------------- #
def test_banded_rotation_rotates_at_threshold():
    """band_tokens=100, est=60 -> A,A,B,B (xoay key khi key active đủ band)."""
    async def run():
        cat, reg, counters = _catalog(), _registry(oai=2), MemoryCounters()
        cap = CapabilityConfig(tiers=["free_oai"], models={"free_oai": "openai/gpt-5.4-mini"})
        sel = _sel("banded_rotation", {"band_tokens": 100}, counters, reg, cat)
        seen = []
        for _ in range(4):
            req = ResolveRequest(capability="think", cap_config=cap, est_tokens=60)
            dec = await sel.resolve(req)
            seen.append(dec.key_id)
        assert seen == ["oai-1", "oai-1", "oai-2", "oai-2"], seen
        print("OK banded rotate:", seen)
    asyncio.run(run())


def test_save_mode_when_all_exhausted():
    """1 key OpenAI limit thấp -> cạn -> save mode ép gpt-4o-mini (daily none -> qua được)."""
    async def run():
        cat = _catalog()
        reg = _registry(oai=1, openr=0, oai_limit=100)
        counters = MemoryCounters()
        cap = CapabilityConfig(tiers=["free_oai"], models={"free_oai": "openai/gpt-5.4-mini"})
        params = {"band_tokens": 250000,
                  "save_mode": {"enabled": True, "model": "openai/gpt-4o-mini", "tier": "free_oai"}}
        sel = _sel("banded_rotation", params, counters, reg, cat)

        def mkreq():
            return ResolveRequest(capability="think", cap_config=cap, est_tokens=60)

        d1 = await sel.resolve(mkreq())   # 60 <= 100 -> gpt-5.4-mini bình thường
        assert d1 is not None and d1.model_id == "openai/gpt-5.4-mini"
        d2 = await sel.resolve(mkreq())   # 60+60>100 -> free_oai reserve fail -> save mode
        assert d2 is not None and d2.model_id == "openai/gpt-4o-mini", d2 and d2.model_id
        assert d2.key_id == "oai-1"       # vẫn key OpenAI
        print("OK save mode:", d2.public())
    asyncio.run(run())


def test_weighted_banded_ratio_4_to_1():
    """lanes gpt(w4)/deepseek(w1) -> 5 request: 4 free_oai + 1 paid."""
    async def run():
        cat = _catalog()
        reg = _registry(oai=1, openr=1)
        counters = MemoryCounters()
        cap = CapabilityConfig(
            tiers=["free_oai", "paid"],
            models={"free_oai": "openai/gpt-5.4-mini", "paid": "deepseek/deepseek-v4-flash"},
            selector=SelectorConfig(impl="weighted_banded"),
        )
        params = {"lanes": [
            {"tier": "free_oai", "weight": 4, "band_tokens": 10_000_000},
            {"tier": "paid", "weight": 1, "band_tokens": 10_000_000},
        ]}
        sel = _sel("weighted_banded", params, counters, reg, cat)
        tiers = []
        for _ in range(5):
            req = ResolveRequest(capability="think", cap_config=cap, est_tokens=50, has_tools=True)
            dec = await sel.resolve(req)
            tiers.append(dec.tier)
        assert tiers.count("free_oai") == 4 and tiers.count("paid") == 1, tiers
        print("OK weighted 4:1:", tiers)
    asyncio.run(run())


def test_reserve_hard_cap_still_blocks():
    """Band KHÔNG phá hard cap: limit 100, est 60 -> request 2 không thể ở free_oai."""
    async def run():
        cat = _catalog()
        reg = _registry(oai=1, openr=0, oai_limit=100)
        counters = MemoryCounters()
        cap = CapabilityConfig(tiers=["free_oai"], models={"free_oai": "openai/gpt-5.4-mini"},
                               selector=None)
        # save mode tắt -> cạn là None (kiểm hard cap thuần)
        sel = _sel("banded_rotation", {"band_tokens": 250000, "save_mode": {"enabled": False}},
                   counters, reg, cat)

        def mkreq():
            return ResolveRequest(capability="think", cap_config=cap, est_tokens=60)

        assert (await sel.resolve(mkreq())) is not None
        assert (await sel.resolve(mkreq())) is None   # 120 > 100 -> chặn, save mode off
        print("OK hard cap blocks")
    asyncio.run(run())


if __name__ == "__main__":
    test_banded_rotation_rotates_at_threshold()
    test_save_mode_when_all_exhausted()
    test_weighted_banded_ratio_4_to_1()
    test_reserve_hard_cap_still_blocks()
    print("\nALL TESTS PASSED")
