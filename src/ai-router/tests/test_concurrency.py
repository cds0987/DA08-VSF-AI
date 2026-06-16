"""Concurrency LOGIC test (1 process, MemoryCounters) — chứng minh bảo đảm router dưới tải.

Bắn nhiều resolve() SONG SONG bằng asyncio.gather, kiểm 3 bảo đảm cốt lõi (PLAN §18):
- KHÔNG overbook: số request đậu free <= quota/est (reserve atomic chặn đúng trần).
- SPILL không QUEUE: mọi user đều có route (cạn free -> tự xuống paid), không ai bị None.
- FAN-OUT: nhiều key OpenAI -> tổng free = Σ quota từng key.

⚠️ Đây là tầng LOGIC (1 process). Atomic THẬT xuyên nhiều gateway-instance do Redis Lua lo
-> cần test riêng với Redis thật (xem test_concurrency_redis, chạy khi có AIROUTER_TEST_REDIS_URL).
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_router.catalog import Catalog
from ai_router.config import CapabilityConfig, RoutingTable, SelectorConfig
from ai_router.counters import MemoryCounters
from ai_router.registry import OPENROUTER_BASE_URL, TIER_DEFS, Registry
from ai_router.schemas import KeyEntry, Limit, ModelEntry, Provider
from ai_router.selector import ResolveRequest, build_selector

EST = 10  # token/req ước lượng


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
    ])


def _table() -> RoutingTable:
    return RoutingTable(
        version=1, selector=SelectorConfig(impl="sticky_rotation_soft"),
        capabilities={"answer": CapabilityConfig(
            tiers=["free_oai", "free_or", "paid"],
            models={"free_oai": "openai/gpt-4o-mini", "free_or": "qwen/qwen3:free",
                    "paid": "deepseek/deepseek-v4-flash"})},
    )


def _registry(oai_keys: int, oai_quota: int, or_req: int) -> Registry:
    keys: list[KeyEntry] = []
    env: dict[str, str] = {}
    for i in range(1, oai_keys + 1):
        keys.append(KeyEntry(id=f"oai-{i}", provider=Provider.OPENAI, base_url=None,
                             api_key_env=f"OPENAI_API_KEY_{i}", tier="free_oai",
                             limit=Limit(kind="tokens_per_day", value=oai_quota)))
        env[f"OPENAI_API_KEY_{i}"] = f"sk-oai-{i}"
    keys.append(KeyEntry(id="or-1", provider=Provider.OPENROUTER, base_url=OPENROUTER_BASE_URL,
                         api_key_env="OPENROUTER_API_KEY_1", tier="free_or",
                         limit=Limit(kind="requests_per_day", value=or_req, rpm=10_000)))
    env["OPENROUTER_API_KEY_1"] = "sk-or"
    return Registry(keys, env)


async def _fire(n: int, registry: Registry) -> list:
    cat, tbl = _catalog(), _table()
    counters = MemoryCounters()
    sel = build_selector("sticky_rotation_soft", registry=registry, catalog=cat,
                         counters=counters, tier_defs=TIER_DEFS, params={})
    cap = tbl.capabilities["answer"]

    async def one():
        req = ResolveRequest(capability="answer", cap_config=cap, est_tokens=EST,
                             has_tools=True, endpoint="chat")
        return await sel.resolve(req)

    return await asyncio.gather(*[one() for _ in range(n)])


def test_no_overbook_and_spill_not_queue():
    """20 user đồng thời, free chỉ đủ 5+3 -> 8 đậu free, 12 spill paid, KHÔNG ai bị từ chối."""
    async def run():
        reg = _registry(oai_keys=1, oai_quota=50, or_req=3)  # free_oai=50/10=5, free_or=3
        decs = await _fire(20, reg)
        assert all(d is not None for d in decs), "có user KHÔNG được phục vụ (queue/drop)"
        tiers = [d.tier for d in decs]
        free_oai = tiers.count("free_oai")
        free_or = tiers.count("free_or")
        paid = tiers.count("paid")
        assert free_oai == 5, f"free_oai={free_oai} (overbook nếu >5)"   # 50/10
        assert free_or == 3, f"free_or={free_or}"
        assert paid == 12, f"paid={paid}"
        assert free_oai * EST <= 50, "OVERBOOK: vượt quota token free_oai"
    asyncio.run(run())


def test_fanout_multikey_total_free_is_sum():
    """3 key OpenAI mỗi key đủ 2 req -> tổng 6 đậu free_oai (fan-out = Σ quota)."""
    async def run():
        reg = _registry(oai_keys=3, oai_quota=20, or_req=0)  # mỗi key 20/10=2 -> tổng 6
        decs = await _fire(10, reg)
        assert all(d is not None for d in decs)
        free_oai = [d for d in decs if d.tier == "free_oai"]
        assert len(free_oai) == 6, f"free_oai tổng={len(free_oai)} (mong đợi 3 key × 2)"
        # mỗi key không vượt trần: <= 2 request/key
        per_key: dict[str, int] = {}
        for d in free_oai:
            per_key[d.key_id] = per_key.get(d.key_id, 0) + 1
        assert all(v <= 2 for v in per_key.values()), f"overbook 1 key: {per_key}"
        assert len(per_key) == 3, f"chưa fan-out đủ 3 key: {per_key}"
    asyncio.run(run())
