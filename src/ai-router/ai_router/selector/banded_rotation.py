"""banded_rotation — selector MẶC ĐỊNH toàn hệ (PLAN §11.2).

Khác sticky_rotation_soft: thay vì dính 1 key tới khi chạm HARD cap (2.5M/RPM) mới tràn,
ở đây cứ key active phục vụ >= band_tokens (mặc định 250K, theo est) thì XOAY sang key kế
-> rải tải đều, giảm burst. Vẫn tôn trọng reserve (RPM + daily hard cap 2.5M).

Cạn MỌI tier -> SAVE MODE: ép gpt-4o-mini trên tier OpenAI (bỏ trần free), vẫn band
-> hệ KHÔNG trả 503 mà degrade rẻ.
"""
from __future__ import annotations

import logging

from ..config import BandedParams
from ..schemas import RouteDecision
from .base import ResolveRequest, Selector

logger = logging.getLogger("ai_router.selector")


class BandedRotation(Selector):
    async def resolve(self, req: ResolveRequest) -> RouteDecision | None:
        p = BandedParams.model_validate(self.params or {})
        # Bậc thang tier cost tăng dần — banded rotation TRONG mỗi tier.
        for tier_name in req.cap_config.tiers:
            dec = await self.banded_tier(req, tier_name, p.band_tokens)
            if dec is not None:
                logger.info("resolved %s", dec.public())
                return dec
        # Mọi tier cạn -> save mode (gpt-4o-mini, OpenAI).
        dec = await self.save_mode(req, p.save_mode)
        if dec is not None:
            logger.info("resolved (save_mode) %s", dec.public())
            return dec
        logger.warning("no_capacity capability=%s", req.capability)
        return None
