"""elastic_banded — selector CO GIÃN theo tải + RẢI ĐỀU trên toàn pool key (PLAN §11.3).

Vấn đề banded/sticky cũ: tối ưu token-locality (rẻ) nhưng dồn 1 'active' key, KHÔNG rải đều
cho concurrency lớn. Ở đây 3 cơ chế gộp lại:

  1. ELASTIC WIDTH (scale ngang DẦN theo nhu cầu): scope giữ cửa sổ W key active. Tải (in-flight
     đồng thời) chạm ngưỡng sức W key -> NỞ W+1; im tải -> CO W-1 (rẻ lại). Không bật hết key khi
     không cần.
  2. EVEN-ROTATION + SWAP (tải ĐỀU trên TỔNG key, không theo token-interval): active set KHÔNG
     phải live[:W] cố định, mà là W key có TẢI TÍCH LŨY (band, cửa sổ trượt 1h) THẤP NHẤT -> key
     dùng nhiều chìm xuống (THAY RA), key nghỉ nổi lên (THAY VÀO) -> đều dần trên toàn pool.
  3. LEAST-INFLIGHT DISPATCH: trong active set, đậu vào key ít in-flight nhất NGAY lúc đó (cân
     bằng tức thời), chiếm 1 slot (router release sau khi xong). Vẫn tôn trọng reserve (RPM+daily).

State sống ở Redis (inflight + width + band) -> nhiều replica ai-router chia sẻ, quyết định
fan-out + rải tải NHẤT QUÁN toàn cục. Cạn mọi tier -> save mode (như banded).

params: slot_per_key (sức 1 key, default 4), grow_at (0.75), shrink_at (0.25),
        save_mode {enabled, model, tier, band_tokens}.
"""
from __future__ import annotations

import logging
import types

from ..schemas import RouteDecision
from .base import ResolveRequest, Selector

logger = logging.getLogger("ai_router.selector")


class ElasticBanded(Selector):
    async def resolve(self, req: ResolveRequest) -> RouteDecision | None:
        slot_per_key = int(self.params.get("slot_per_key", 4))
        grow_at = float(self.params.get("grow_at", 0.75))
        shrink_at = float(self.params.get("shrink_at", 0.25))
        for tier_name in req.cap_config.tiers:
            dec = await self._elastic_tier(req, tier_name, slot_per_key, grow_at, shrink_at)
            if dec is not None:
                logger.info("resolved %s", dec.public())
                return dec
        sm = self.params.get("save_mode") or {}
        cfg = types.SimpleNamespace(
            enabled=sm.get("enabled", False), model=sm.get("model"),
            tier=sm.get("tier"), band_tokens=int(sm.get("band_tokens", 150000)),
        )
        dec = await self.save_mode(req, cfg)
        if dec is not None:
            logger.info("resolved (save_mode) %s", dec.public())
            return dec
        logger.warning("no_capacity capability=%s", req.capability)
        return None

    async def _elastic_tier(self, req: ResolveRequest, tier_name: str,
                            slot_per_key: int, grow_at: float, shrink_at: float) -> RouteDecision | None:
        tdef = self.tier_defs.get(tier_name)
        if tdef is None:
            return None
        keys = self.registry.keys_for_provider(tdef.provider)
        live = [k for k in keys
                if not await self.counters.in_cooldown(k.id)
                and not await self.counters.is_drained(k.id)]
        if not live:
            return None
        scope = f"{req.capability}:{tier_name}"
        n = len(live)

        # snapshot tải: in-flight (tức thời) + band (tích lũy 1h) cho mọi key sống.
        inflight = {k.id: await self.counters.get_inflight(k.id) for k in live}
        band = {k.id: await self.counters.get_band(scope, k.id) for k in live}

        # WIDTH co giãn theo TỔNG in-flight toàn pool so với sức W key active (phát hiện
        # tải thật vượt sức "W cặp đang bật" -> nở; tải rút -> co).
        W = max(1, min(await self.counters.get_width(scope), n))
        total_inflight = sum(inflight[k.id] for k in live)
        cap = W * slot_per_key
        util = (total_inflight / cap) if cap else 1.0
        if util >= grow_at and W < n:
            W += 1
            await self.counters.set_width(scope, W)
            self._emit("airouter_fanout_grow_total", {"scope": scope, "width": str(W)})
        elif util <= shrink_at and W > 1:
            W -= 1
            await self.counters.set_width(scope, W)
            self._emit("airouter_fanout_shrink_total", {"scope": scope, "width": str(W)})

        # EVEN-ROTATION: active = W key tải-tích-lũy thấp nhất (band) -> thay-ra-thay-vào đều.
        active = sorted(live, key=lambda k: (band[k.id], inflight[k.id]))[:W]
        # DISPATCH: trong active, ưu tiên ít in-flight nhất (cân bằng tức thời), rồi band thấp.
        order = sorted(active, key=lambda k: (inflight[k.id], band[k.id]))

        model = await self.pick_model(tier_name, tdef, req)
        if model is None:
            return None  # tier không có model khả thi -> spill tier kế
        for k in order:
            # slot in-flight TRƯỚC (cổng concurrency rẻ); đầy -> key kế trong cửa sổ.
            token = await self.counters.acquire_inflight(k.id, max_inflight=slot_per_key)
            if token is None:
                continue
            daily_limit = k.limit.value if tdef.limit_kind != "none" else 0.0
            ok = await self.counters.reserve(
                k.id, rpm_limit=tdef.rpm, daily_kind=tdef.limit_kind,
                daily_limit=daily_limit, est_tokens=req.est_tokens,
            )
            if not ok:
                await self.counters.release_inflight(k.id, token)
                continue
            await self.counters.add_band(scope, k.id, req.est_tokens)  # rolling load (even/swap)
            dec = self.build_decision(k, model, tier_name, req)
            dec.inflight_token = token
            return dec
        return None  # cả cửa sổ bão hoà slot/quota -> tier kế
