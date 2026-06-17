"""Test control-plane HITL v1: drain key (selector loại key, guardrail key cuối, resume).

Chạy: python -m pytest tests/test_drain.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_router.catalog import Catalog
from ai_router.config import CapabilityConfig, Settings
from ai_router.counters import MemoryCounters
from ai_router.registry import OPENROUTER_BASE_URL, TIER_DEFS, Registry
from ai_router.router import Router
from ai_router.schemas import KeyEntry, Limit, ModelEntry, Provider
from ai_router.selector import ResolveRequest, build_selector


def _catalog() -> Catalog:
    return Catalog([
        ModelEntry(id="openai/gpt-5.4-mini", provider="openai", name_native="gpt-5.4-mini",
                   name_or="openai/gpt-5.4-mini", context_length=400000, supports_tools=True,
                   endpoint="chat"),
    ])


def _registry(n=2) -> Registry:
    keys, env = [], {}
    for i in range(1, n + 1):
        keys.append(KeyEntry(id=f"oai-{i}", provider=Provider.OPENAI, base_url=None,
                             api_key_env=f"OPENAI_API_KEY_{i}", tier="free_oai",
                             limit=Limit(kind="tokens_per_day", value=2_500_000)))
        env[f"OPENAI_API_KEY_{i}"] = f"sk-{i}"
    return Registry(keys, env)


def test_drained_key_excluded_from_selector():
    async def run():
        cat, reg, counters = _catalog(), _registry(2), MemoryCounters()
        cap = CapabilityConfig(tiers=["free_oai"], models={"free_oai": "openai/gpt-5.4-mini"})
        sel = build_selector("banded_rotation", registry=reg, catalog=cat, counters=counters,
                             tier_defs=TIER_DEFS, params={"band_tokens": 10_000_000})
        await counters.set_drain("oai-1", 3600)
        for _ in range(3):
            dec = await sel.resolve(ResolveRequest(capability="think", cap_config=cap, est_tokens=50))
            assert dec is not None and dec.key_id == "oai-2"  # oai-1 drained -> luôn oai-2
        print("OK selector loại key drained")
    asyncio.run(run())


def test_drain_resume_and_guardrail():
    async def run():
        r = Router(Settings())          # routing.yaml/catalog từ đĩa (CWD = ai-router)
        r.registry = _registry(2)
        r.counters = MemoryCounters()

        ok = await r.drain_key("oai-1", actor="test", reason="maintenance")
        assert ok["ok"] and ok["drained"] and await r.counters.is_drained("oai-1")

        # guardrail: oai-2 là key SỐNG cuối cùng -> từ chối drain
        refused = await r.drain_key("oai-2")
        assert not refused["ok"] and "last live" in refused["error"]
        assert not await r.counters.is_drained("oai-2")

        # resume oai-1
        res = await r.resume_key("oai-1")
        assert res["ok"] and not await r.counters.is_drained("oai-1")

        # key không tồn tại
        assert not (await r.drain_key("nope"))["ok"]
        print("OK drain/resume + guardrail key cuối")
    asyncio.run(run())


def test_snapshot_has_drained_field():
    async def run():
        r = Router(Settings())
        r.registry = _registry(2)
        r.counters = MemoryCounters()
        await r.drain_key("oai-1", actor="test")
        snap = await r.snapshot()
        by_id = {k["key_id"]: k for k in snap["keys"]}
        assert by_id["oai-1"]["drained"] is True
        assert by_id["oai-2"]["drained"] is False
        print("OK snapshot field drained")
    asyncio.run(run())


if __name__ == "__main__":
    test_drained_key_excluded_from_selector()
    test_drain_resume_and_guardrail()
    test_snapshot_has_drained_field()
    print("\nALL TESTS PASSED")
