"""weighted_banded — strategy RIÊNG cho node `think` (PLAN §11.2, blend).

Mỗi capability cấu hình danh sách LANE = (tier, weight, band_tokens). Selector:
  1) chọn lane bằng WEIGHTED round-robin (bộ đếm next_seq atomic theo capability),
  2) banded key rotation TRONG lane đó (như banded_rotation),
  3) lane chọn cạn -> spill sang các lane còn lại (theo thứ tự config = cost ladder),
  4) cạn hết -> SAVE MODE (gpt-4o-mini, OpenAI).

think:
  - lane A: gpt-5.4-mini @ free_oai, weight 4, band 250K
  - lane B: deepseek-v4-flash @ paid(OpenRouter), weight 1, band 150K
  -> cứ ~5 request: 4 gpt + 1 deepseek. Mỗi lane xoay key theo band riêng.
"""
from __future__ import annotations

import logging

from ..config import LaneConfig, WeightedBandedParams
from ..schemas import RouteDecision
from .base import ResolveRequest, Selector

logger = logging.getLogger("ai_router.selector")


class WeightedBanded(Selector):
    async def resolve(self, req: ResolveRequest) -> RouteDecision | None:
        p = WeightedBandedParams.model_validate(self.params or {})
        lanes = p.lanes or [LaneConfig(tier=t) for t in req.cap_config.tiers]
        if not lanes:
            return None

        seq = await self.counters.next_seq(f"{req.capability}:wrr")
        order = self._weighted_order(lanes, seq)
        for lane in order:
            dec = await self.banded_tier(req, lane.tier, lane.band_tokens)
            if dec is not None:
                logger.info("resolved (lane=%s) %s", lane.tier, dec.public())
                return dec

        dec = await self.save_mode(req, p.save_mode)
        if dec is not None:
            logger.info("resolved (save_mode) %s", dec.public())
            return dec
        logger.warning("no_capacity capability=%s", req.capability)
        return None

    @staticmethod
    def _weighted_order(lanes: list[LaneConfig], seq: int) -> list[LaneConfig]:
        """Weighted round-robin: vị trí seq trong tổng weight -> lane được chọn ĐẦU TIÊN;
        các lane còn lại nối theo thứ tự config (cost ladder) làm spill order."""
        total = sum(max(1, lane.weight) for lane in lanes)
        pos = seq % total
        acc = 0
        chosen = 0
        for i, lane in enumerate(lanes):
            acc += max(1, lane.weight)
            if pos < acc:
                chosen = i
                break
        return [lanes[chosen]] + [l for i, l in enumerate(lanes) if i != chosen]
