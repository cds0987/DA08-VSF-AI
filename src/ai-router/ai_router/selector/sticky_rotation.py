"""sticky_rotation_soft — chiến lược (b) user chốt (PLAN §5.9).

Một key 'active' phục vụ tới khi chạm ngưỡng (RPM/quota) → tràn (soft) sang key kế NGAY,
con trỏ active đi theo key vừa nhận. Bậc thang tier theo cost: free_oai → free_or → paid.
"""
from __future__ import annotations

import logging

from ..schemas import RouteDecision
from .base import ResolveRequest, Selector

logger = logging.getLogger("ai_router.selector")


class StickyRotationSoft(Selector):
    async def resolve(self, req: ResolveRequest) -> RouteDecision | None:
        for tier_name in req.cap_config.tiers:
            tdef = self.tier_defs.get(tier_name)
            if tdef is None:
                continue
            keys = self.registry.keys_for_provider(tdef.provider)
            if not keys:
                continue

            # loại key đang cooling-down (429)
            live = [k for k in keys if not await self.counters.in_cooldown(k.id)]
            if not live:
                continue

            # sticky: bắt đầu từ con trỏ active của (capability, tier), rồi xoay (soft overflow)
            ptr_name = f"{req.capability}:{tier_name}"
            active = await self.counters.get_active(ptr_name) % len(live)
            order = live[active:] + live[:active]

            for k in order:
                model = self.pick_model(tier_name, tdef, req)
                if model is None:
                    break  # tier này không có model khả thi cho request -> sang tier kế
                daily_limit = k.limit.value if tdef.limit_kind != "none" else 0.0
                ok = await self.counters.reserve(
                    k.id, rpm_limit=tdef.rpm, daily_kind=tdef.limit_kind,
                    daily_limit=daily_limit, est_tokens=req.est_tokens,
                )
                if ok:
                    await self.counters.set_active(ptr_name, live.index(k))
                    dec = self.build_decision(k, model, tier_name, req)
                    logger.info("resolved %s", dec.public())
                    return dec
                # key này chạm ngưỡng -> thử key kế (soft overflow)
            # cả tier bão hoà -> tier kế (spill)
        logger.warning("no_capacity capability=%s", req.capability)
        return None
