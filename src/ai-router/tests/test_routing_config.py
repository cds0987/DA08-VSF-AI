"""Gate CI: routing.yaml PHẢI khớp model_catalog.json + resolve được mọi capability.

Đây là lớp "đảm bảo router chạy ổn" TRƯỚC khi đẩy production (offline, không gọi mạng):
- Mọi model id trong routing.yaml tồn tại trong catalog (chặn gõ sai tên).
- Mỗi (capability, tier, model) KHẢ THI đúng ràng buộc tier: provider-split, free/paid,
  vision (ocr/caption), tools, endpoint (embed=embeddings).
- pinned_model embed tồn tại + đúng endpoint.
- resolve() trả RouteDecision != None cho MỌI capability (free key dư) -> không "no capacity"
  vì cấu hình sai.
- Interchange: model free_or đầu bị cooldown -> resolve tự nhảy model kế (không vỡ).

Chạy: python -m pytest tests/test_routing_config.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_router.catalog import load_catalog
from ai_router.config import load_routing_table
from ai_router.counters import MemoryCounters
from ai_router.registry import TIER_DEFS, Registry
from ai_router.schemas import Provider
from ai_router.selector import ResolveRequest, build_selector

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTING_PATH = os.path.join(_ROOT, "routing.yaml")
CATALOG_PATH = os.path.join(_ROOT, "config", "model_catalog.json")

CATALOG = load_catalog(CATALOG_PATH)
TABLE = load_routing_table(ROUTING_PATH)
SUPPLEMENT_PATH = os.path.join(_ROOT, "config", "openai_supplement.json")

# env giả: 1 key OpenAI + 1 key OpenRouter (key OpenRouter phục vụ cả free_or lẫn paid).
_FAKE_ENV = {"OPENAI_API_KEY_1": "sk-test-oai", "OPENROUTER_API_KEY_1": "sk-test-or"}


def _endpoint_for_tier(tier_name: str) -> str:
    for t in TABLE.tiers:
        if t.name == tier_name:
            return t.endpoint_default
    return "chat"


def _all_model_ids(cap) -> list[tuple[str, str]]:
    """[(tier, model_id)] gồm cả pinned_model."""
    out: list[tuple[str, str]] = []
    if cap.pinned_model:
        out.append(("(pinned)", cap.pinned_model))
    for tier in cap.tiers:
        for mid in cap.model_ids(tier):
            out.append((tier, mid))
    return out


def test_catalog_non_empty():
    assert len(CATALOG) > 0, f"catalog rỗng: {CATALOG_PATH}"


def test_every_tier_defined():
    for name, cap in TABLE.capabilities.items():
        for tier in cap.tiers:
            assert tier in TIER_DEFS, f"{name}: tier '{tier}' chưa định nghĩa trong TIER_DEFS"


def test_referenced_models_exist_in_catalog():
    missing: list[str] = []
    for name, cap in TABLE.capabilities.items():
        for tier, mid in _all_model_ids(cap):
            if CATALOG.get(mid) is None:
                missing.append(f"{name}/{tier}: '{mid}'")
    assert not missing, "model id KHÔNG có trong catalog (gõ sai tên?):\n  " + "\n  ".join(missing)


def test_non_chat_models_in_supplement_survive_catalog_rebuild():
    """build_catalog.py fetch OpenRouter /models -> GHI ĐÈ catalog. /models chỉ có model
    chat/completion; model endpoint embeddings/rerank KHÔNG có -> sẽ BỊ DROP khi rebuild nếu
    không nằm trong openai_supplement.json (được merge lại). Test: mọi model của capability
    có endpoint != chat PHẢI nằm trong supplement -> tồn tại sau rebuild ở prod.
    (Regression: cohere/rerank-4-pro từng chỉ ở catalog committed -> rebuild drop -> rerank 503.)"""
    import json
    sup_ids = {m["id"] for m in json.loads(Path(SUPPLEMENT_PATH).read_text(encoding="utf-8"))}
    missing: list[str] = []
    for name, cap in TABLE.capabilities.items():
        ep = "embeddings" if cap.pinned_model else cap.endpoint
        if ep == "chat":
            continue
        for _tier, mid in _all_model_ids(cap):
            if mid not in sup_ids:
                missing.append(f"{name} ({ep}) '{mid}'")
    assert not missing, ("model endpoint non-chat KHÔNG nằm trong openai_supplement.json -> "
                         "sẽ bị build_catalog drop khi rebuild:\n  " + "\n  ".join(missing))


def test_models_feasible_for_their_tier():
    """Mỗi model chỉ định phải QUA được ràng buộc tier -> tránh 'âm thầm rớt về auto'."""
    bad: list[str] = []
    for name, cap in TABLE.capabilities.items():
        for tier, mid in _all_model_ids(cap):
            m = CATALOG.get(mid)
            if m is None:
                continue  # đã bắt ở test trên
            tname = cap.tiers[0] if tier == "(pinned)" else tier
            tdef = TIER_DEFS.get(tname)
            if tdef is None:
                continue
            ep = "embeddings" if cap.pinned_model and tier == "(pinned)" else cap.endpoint
            if tdef.provider == Provider.OPENAI and m.provider != "openai":
                bad.append(f"{name}/{tier} '{mid}': provider!={Provider.OPENAI.value} (OpenAI key chỉ gọi model openai)")
            if tdef.model_free is not None and m.is_free != tdef.model_free:
                bad.append(f"{name}/{tier} '{mid}': is_free={m.is_free} nhưng tier yêu cầu free={tdef.model_free}")
            if cap.require_vision and not m.is_vision():
                bad.append(f"{name}/{tier} '{mid}': KHÔNG vision nhưng capability require_vision")
            if cap.require_tools and not m.supports_tools:
                bad.append(f"{name}/{tier} '{mid}': KHÔNG tool nhưng capability require_tools")
            if m.endpoint != ep:
                bad.append(f"{name}/{tier} '{mid}': endpoint={m.endpoint} != tier endpoint={ep}")
    assert not bad, "model không khả thi cho tier đã gán:\n  " + "\n  ".join(bad)


def _selector():
    reg = Registry.from_env(_FAKE_ENV)
    return build_selector(TABLE.selector.impl, registry=reg, catalog=CATALOG,
                          counters=MemoryCounters(), tier_defs=TIER_DEFS, params=TABLE.selector.params), reg


@pytest.mark.parametrize("cap_name", list(TABLE.capabilities.keys()))
def test_every_capability_resolves(cap_name):
    """Free key dư -> phải resolve ra route hợp lệ; None = cấu hình sai gây 'no capacity'."""
    async def run():
        sel, _ = _selector()
        cap = TABLE.capabilities[cap_name]
        endpoint = "embeddings" if cap.pinned_model else cap.endpoint
        req = ResolveRequest(
            capability=cap_name, cap_config=cap, est_tokens=50,
            has_tools=cap.require_tools, has_image=cap.require_vision, endpoint=endpoint,
        )
        dec = await sel.resolve(req)
        assert dec is not None, f"capability '{cap_name}' KHÔNG resolve được route nào"
        assert CATALOG.get(dec.model_id) is not None
    asyncio.run(run())


def test_free_or_interchange_failover():
    """free_or model đầu bị cooldown -> resolve nhảy sang model kế trong danh sách."""
    async def run():
        # chọn 1 capability có danh sách free_or >= 2 model
        target = next(
            (n for n, c in TABLE.capabilities.items() if len(c.model_ids("free_or")) >= 2),
            None,
        )
        if target is None:
            pytest.skip("không capability nào có free_or interchange list")
        cap = TABLE.capabilities[target]
        ids = cap.model_ids("free_or")
        counters = MemoryCounters()
        reg = Registry.from_env(_FAKE_ENV)
        sel = build_selector(TABLE.selector.impl, registry=reg, catalog=CATALOG,
                             counters=counters, tier_defs=TIER_DEFS, params=TABLE.selector.params)
        # cạn free_oai để ép xuống free_or: cooldown mọi key OpenAI
        for k in reg.keys_for_provider(Provider.OPENAI):
            await counters.set_cooldown(k.id, 60)
        # cooldown model free_or đầu tiên
        await counters.set_model_cooldown(ids[0], 60)
        req = ResolveRequest(capability=target, cap_config=cap, est_tokens=50,
                             has_tools=cap.require_tools, endpoint="chat")
        dec = await sel.resolve(req)
        assert dec is not None
        assert dec.model_id != ids[0], f"vẫn chọn model đang cooldown {ids[0]}"
        assert dec.tier == "free_or" and dec.model_id in ids[1:]
    asyncio.run(run())
