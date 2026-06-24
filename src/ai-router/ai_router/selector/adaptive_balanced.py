"""adaptive_balanced — load-balance theo BẢN CHẤT TỪNG LOẠI KEY (PLAN §11.4).

Hai loại key có trần KHÁC NHAU -> KHÔNG dùng chung 1 con số:

  OpenAI key  : có TPM (token/phút) RÕ -> chọn key còn nhiều TPM-headroom nhất,
                gate = tpm_reserve(est ≤ TPM). "tải đều theo token/phút".
  OpenRouter  : multiplex ~15 upstream -> KHÔNG có TPM cố định -> AIMD tự DÒ trần:
                limit động/key (grow khi success, ×0.5 khi 429-rate). chọn key
                (limit−inflight) lớn nhất, gate = inflight < limit. "đa nhà cung cấp,
                tự học sức thật". (router hook aimd_grow/shrink ở account/_handle_error.)

KHÔNG ai chờ ai: 1 key nhận nhiều request đồng loạt tới khi chạm trần THẬT (TPM hoặc
limit AIMD), mới sang key kế; cạn pool -> save_mode (gpt-4o-mini OpenAI), không 503.
State sống ở Redis -> nhiều replica ai-router cùng quyết định.
"""
from __future__ import annotations

import logging
import types

from ..schemas import Provider, RouteDecision
from .base import ResolveRequest, Selector

logger = logging.getLogger("ai_router.selector")


class AdaptiveBalanced(Selector):
    async def resolve(self, req: ResolveRequest) -> RouteDecision | None:
        tpm = int(self.params.get("tpm_per_key", 500_000))
        for tier_name in req.cap_config.tiers:
            dec = await self._tier(req, tier_name, tpm)
            if dec is not None:
                logger.info("resolved %s", dec.public())
                return dec
        sm = self.params.get("save_mode") or {}
        cfg = types.SimpleNamespace(
            enabled=sm.get("enabled", False), model=sm.get("model"),
            tier=sm.get("tier"), band_tokens=int(sm.get("band_tokens", 150_000)),
        )
        dec = await self.save_mode(req, cfg)
        if dec is not None:
            logger.info("resolved (save_mode) %s", dec.public())
            return dec
        logger.warning("no_capacity capability=%s", req.capability)
        return None

    async def _tier(self, req: ResolveRequest, tier_name: str, tpm: int) -> RouteDecision | None:
        tdef = self.tier_defs.get(tier_name)
        if tdef is None:
            return None
        keys = self.registry.keys_for_provider(tdef.provider)
        live = [k for k in keys
                if not await self.counters.in_cooldown(k.id)
                and not await self.counters.is_drained(k.id)]
        if not live:
            return None
        model = await self._pick_model_split(tier_name, tdef, req)
        if model is None:
            return None
        is_oai = tdef.provider == Provider.OPENAI

        # ── XẾP HẠNG theo headroom (least-loaded) — tín hiệu khác nhau theo provider ──
        ranked: list = []
        for k in live:
            if is_oai:
                t = await self.counters.get_tpm(k.id)
                if t + req.est_tokens > tpm:
                    continue                      # key này hết TPM phút -> bỏ
                ranked.append((t, k))             # ít token/phút nhất lên đầu
            else:
                lim = await self.counters.get_aimd_limit(k.id)
                inf = await self.counters.get_inflight(k.id)
                if inf >= lim:
                    continue                      # đầy theo limit AIMD -> bỏ
                ranked.append((inf - lim, k))     # nhiều headroom nhất (âm nhất) lên đầu
        ranked.sort(key=lambda x: x[0])

        for _, k in ranked:
            # GATE theo trần thật + chiếm chỗ
            token = None
            if is_oai:
                if not await self.counters.tpm_reserve(k.id, amount=req.est_tokens, tpm_limit=tpm):
                    continue
            else:
                lim = int(await self.counters.get_aimd_limit(k.id))
                token = await self.counters.acquire_inflight(k.id, max_inflight=lim)
                if token is None:
                    continue
            # backstop: RPM + trần ngày (quota cứng) vẫn áp
            daily_limit = k.limit.value if tdef.limit_kind != "none" else 0.0
            ok = await self.counters.reserve(
                k.id, rpm_limit=tdef.rpm, daily_kind=tdef.limit_kind,
                daily_limit=daily_limit, est_tokens=req.est_tokens,
            )
            if not ok:
                await self.counters.release_inflight(k.id, token)   # token None -> no-op
                continue
            dec = self.build_decision(k, model, tier_name, req)
            dec.inflight_token = token            # OR: router release + aimd_grow sau call
            return dec
        return None

    async def _pick_model_split(self, tier_name, tdef, req):
        """CHIA TẢI model (//hóa): nhiều model cấu hình cho 1 tier -> ROUND-ROBIN (vd deepseek 50%
        + xiaomi 50%) thay vì failover-first. deepseek/xiaomi là 2 upstream GPU KHÁC nhau -> chia
        đôi -> mỗi upstream nửa tải -> queue inference NÔNG hơn -> p99 ttfc THẤP hơn (gốc 12s là
        queue upstream, KHÔNG phải credential/key). Cùng pool OR key nên AIMD vẫn cân key bình thường.
        pinned -> pin; 0 khả thi -> auto rẻ nhất; bỏ model đang cooldown."""
        if req.cap_config.pinned_model:
            m = self.catalog.get(req.cap_config.pinned_model)
            return m if self.feasible_model(m, tdef, req) else None
        cands = []
        for mid in req.cap_config.model_ids(tier_name):
            m = self.catalog.get(mid)
            if m and self.feasible_model(m, tdef, req) and not await self.counters.in_model_cooldown(m.id):
                cands.append(m)
        if not cands:
            return await self.pick_model(tier_name, tdef, req)
        if len(cands) == 1:
            return cands[0]
        seq = await self.counters.next_seq(f"{req.capability}:{tier_name}:msplit")
        return cands[seq % len(cands)]
