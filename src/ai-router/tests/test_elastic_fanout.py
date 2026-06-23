"""Test selector elastic_banded (offline, MemoryCounters) — 3 tính chất:

1. ELASTIC: tải (in-flight giữ) tăng -> width NỞ dần 1->n; giải phóng -> CO lại.
2. EVEN: tải rải ĐỀU trên TỔNG key (không dồn 1 key).
3. SWAP/rotation: ở tải nhẹ (W nhỏ) vẫn luân phiên đều mọi key theo thời gian.

Chạy: python -m pytest tests/test_elastic_fanout.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_router.catalog import Catalog
from ai_router.config import CapabilityConfig
from ai_router.counters import MemoryCounters
from ai_router.registry import TIER_DEFS, Registry
from ai_router.schemas import KeyEntry, Limit, ModelEntry, Provider
from ai_router.selector import ResolveRequest, build_selector

SCOPE = "answer:free_oai"
EST = 10


def _catalog() -> Catalog:
    return Catalog([
        ModelEntry(id="openai/gpt-4o-mini", provider="openai", name_native="gpt-4o-mini",
                   name_or="openai/gpt-4o-mini", context_length=128000, supports_tools=True,
                   is_free=False, endpoint="chat"),
    ])


def _registry(n: int, quota: int = 10_000_000) -> Registry:
    keys, env = [], {}
    for i in range(1, n + 1):
        keys.append(KeyEntry(id=f"oai-{i}", provider=Provider.OPENAI, base_url=None,
                             api_key_env=f"OPENAI_API_KEY_{i}", tier="free_oai",
                             limit=Limit(kind="tokens_per_day", value=quota)))
        env[f"OPENAI_API_KEY_{i}"] = f"sk-{i}"
    return Registry(keys, env)


def _sel(counters, reg):
    cap = CapabilityConfig(tiers=["free_oai"], models={"free_oai": "openai/gpt-4o-mini"})
    sel = build_selector("elastic_banded", registry=reg, catalog=_catalog(), counters=counters,
                         tier_defs=TIER_DEFS,
                         params={"slot_per_key": 2, "grow_at": 0.75, "shrink_at": 0.25})
    return sel, cap


def _req(cap):
    return ResolveRequest(capability="answer", cap_config=cap, est_tokens=EST, endpoint="chat")


def test_elastic_grows_then_shrinks_and_spreads_even():
    async def run():
        counters = MemoryCounters()
        sel, cap = _sel(counters, _registry(4))

        # --- TẢI TĂNG: giữ 8 request (= 4 key × 2 slot), KHÔNG release -> width phải NỞ dần ---
        held, widths = [], []
        for _ in range(8):
            dec = await sel.resolve(_req(cap))
            assert dec is not None, "request không được phục vụ khi pool còn chỗ"
            assert dec.inflight_token, "thiếu slot token để release"
            held.append(dec)
            widths.append(await counters.get_width(SCOPE))

        assert widths[0] == 1, f"khởi đầu phải hẹp (W=1): {widths}"
        assert widths == sorted(widths), f"width phải NỞ đơn điệu theo tải: {widths}"
        assert max(widths) == 4, f"tải đầy pool -> W phải nở tới {4}: {widths}"

        # EVEN: 8 hold rải đều 4 key -> mỗi key đúng 2 (không dồn).
        dist = Counter(d.key_id for d in held)
        assert len(dist) == 4 and all(v == 2 for v in dist.values()), f"không đều: {dist}"

        # pool đầy slot -> request kế phải bị từ chối ở tier (None) — không overbook concurrency.
        assert (await sel.resolve(_req(cap))) is None, "overbook: vượt tổng slot pool"

        # --- TẢI RÚT: release hết, resolve+release ngay nhiều lần -> width CO lại về 1 ---
        for d in held:
            await counters.release_inflight(d.key_id, d.inflight_token)
        shrink = []
        for _ in range(6):
            dec = await sel.resolve(_req(cap))
            await counters.release_inflight(dec.key_id, dec.inflight_token)
            shrink.append(await counters.get_width(SCOPE))
        assert shrink[-1] == 1, f"tải nhẹ -> width phải co về 1 (rẻ lại): {shrink}"
        print("OK elastic grow/shrink:", widths, "->", shrink, "| dist", dict(dist))

    asyncio.run(run())


def test_light_load_rotates_evenly_across_all_keys():
    """Tải nhẹ (release ngay -> W=1) nhưng VẪN luân phiên đều mọi key (swap theo band)."""
    async def run():
        counters = MemoryCounters()
        sel, cap = _sel(counters, _registry(4))
        dist = Counter()
        for _ in range(12):                      # 12 request tuần tự, mỗi cái xong ngay
            dec = await sel.resolve(_req(cap))
            await counters.release_inflight(dec.key_id, dec.inflight_token)
            dist[dec.key_id] += 1
        assert await counters.get_width(SCOPE) == 1, "tải nhẹ phải giữ W=1 (không bật thừa key)"
        # 12 / 4 key = 3 mỗi key; even-rotation -> lệch tối đa 1.
        assert all(2 <= v <= 4 for v in dist.values()) and len(dist) == 4, f"không đều: {dist}"
        print("OK light-load even rotation:", dict(dist))

    asyncio.run(run())


if __name__ == "__main__":
    test_elastic_grows_then_shrinks_and_spreads_even()
    test_light_load_rotates_evenly_across_all_keys()
    print("\nALL ELASTIC TESTS PASSED")
