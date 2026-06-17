"""Selector interface + ResolveRequest (PLAN §5.0)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..catalog import Catalog
from ..config import CapabilityConfig
from ..counters import Counters
from ..registry import Registry, TierDef
from ..schemas import ModelEntry, Provider, RouteDecision


@dataclass
class ResolveRequest:
    capability: str
    cap_config: CapabilityConfig
    est_tokens: int
    has_tools: bool = False
    has_image: bool = False
    conversation_id: str | None = None
    user_id: str | None = None
    endpoint: str = "chat"


class Selector(ABC):
    """Bộ não: tín hiệu sống -> 1 RouteDecision. PLAN §5.0."""

    def __init__(self, *, registry: Registry, catalog: Catalog, counters: Counters,
                 tier_defs: dict[str, TierDef], params: dict | None = None,
                 metrics=None) -> None:
        self.registry = registry
        self.catalog = catalog
        self.counters = counters
        self.tier_defs = tier_defs
        self.params = params or {}
        self.metrics = metrics            # observ strategy (band-rotation/save-mode); None = off

    @abstractmethod
    async def resolve(self, req: ResolveRequest) -> RouteDecision | None:
        """Trả (key,base_url,model) hoặc None nếu cạn mọi tier khả thi."""

    # ----- helpers dùng chung -----
    def _emit(self, name: str, labels: dict | None = None) -> None:
        if self.metrics is not None:
            self.metrics.inc(name, labels or {})

    async def banded_tier(
        self, req: ResolveRequest, tier_name: str, band_tokens: int, *,
        scope: str | None = None, model_override: ModelEntry | None = None,
        daily_kind: str | None = None,
    ) -> RouteDecision | None:
        """BANDED key rotation trong 1 tier: dính key active tới khi nó phục vụ >= band_tokens
        (est) thì tiến con trỏ + reset band, rồi reserve (vẫn tôn trọng RPM + daily hard cap).
        Dùng chung cho banded_rotation, weighted_banded (mỗi lane), và save mode.

        model_override: ép 1 model (save mode = gpt-4o-mini). daily_kind: override limit_kind
        của tier (save mode = 'none' -> bỏ trần free, chấp nhận paid)."""
        tdef = self.tier_defs.get(tier_name)
        if tdef is None:
            return None
        keys = self.registry.keys_for_provider(tdef.provider)
        # Loại key đang cooldown (429) HOẶC bị drain (human-in-the-loop rút ra).
        live = [k for k in keys
                if not await self.counters.in_cooldown(k.id)
                and not await self.counters.is_drained(k.id)]
        if not live:
            return None
        scope = scope or f"{req.capability}:{tier_name}"
        active = (await self.counters.get_active(scope)) % len(live)
        cur = live[active]
        # Banded: key active đã đủ band -> reset + tiến con trỏ sang key kế.
        if (await self.counters.get_band(scope, cur.id)) >= band_tokens:
            await self.counters.reset_band(scope, cur.id)
            active = (active + 1) % len(live)
            self._emit("airouter_band_rotation_total", {"scope": scope, "tier": tier_name})
        order = live[active:] + live[:active]
        for k in order:
            if model_override is not None:
                model = model_override if self.feasible_model(model_override, tdef, req) else None
            else:
                model = await self.pick_model(tier_name, tdef, req)
            if model is None:
                break  # tier/lane không có model khả thi -> spill sang tier/lane kế
            dk = daily_kind or tdef.limit_kind
            daily_limit = k.limit.value if dk != "none" else 0.0
            ok = await self.counters.reserve(
                k.id, rpm_limit=tdef.rpm, daily_kind=dk,
                daily_limit=daily_limit, est_tokens=req.est_tokens,
            )
            if ok:
                await self.counters.set_active(scope, live.index(k))
                await self.counters.add_band(scope, k.id, req.est_tokens)
                return self.build_decision(k, model, tier_name, req)
            # key chạm ngưỡng -> thử key kế (soft overflow trong lane)
        return None

    async def save_mode(self, req: ResolveRequest, cfg) -> RouteDecision | None:
        """Save mode: MỌI tier cạn -> ép gpt-4o-mini trên tier OpenAI, bỏ trần free
        (daily_kind='none'), vẫn band. KHÔNG trả 503 mà degrade rẻ."""
        if cfg is None or not getattr(cfg, "enabled", False):
            return None
        model = self.catalog.get(cfg.model)
        if model is None:
            return None
        dec = await self.banded_tier(
            req, cfg.tier, cfg.band_tokens, scope=f"{req.capability}:save",
            model_override=model, daily_kind="none",
        )
        if dec is not None:
            self._emit("airouter_save_mode_total", {"capability": req.capability})
        return dec

    # ----- helpers cũ -----
    def feasible_model(self, m: ModelEntry | None, tdef: TierDef, req: ResolveRequest) -> bool:
        if m is None:
            return False
        if tdef.provider == Provider.OPENAI and m.provider != "openai":
            return False  # provider-split (PLAN §5.4)
        if tdef.model_free is not None and m.is_free != tdef.model_free:
            return False
        if (req.has_tools or req.cap_config.require_tools) and not m.supports_tools:
            return False
        if req.cap_config.require_vision and not m.is_vision():
            return False
        if req.est_tokens and m.context_length and m.context_length < req.est_tokens:
            return False
        if m.endpoint != req.endpoint:
            return False
        return True

    async def pick_model(self, tier_name: str, tdef: TierDef, req: ResolveRequest) -> ModelEntry | None:
        # 1) embed -> PIN (BẪY embedding, PLAN §4b)
        if req.cap_config.pinned_model:
            m = self.catalog.get(req.cap_config.pinned_model)
            return m if self.feasible_model(m, tdef, req) else None
        # 2) danh sách model chỉ định cho tier (interchange/failover): thử lần lượt,
        #    bỏ model không khả thi/biến mất hoặc đang cooldown (vừa lỗi/sập) -> model kế.
        for mid in req.cap_config.model_ids(tier_name):
            m = self.catalog.get(mid)
            if m and self.feasible_model(m, tdef, req) and not await self.counters.in_model_cooldown(m.id):
                return m
        # 3) auto: ứng viên rẻ nhất khả thi, cũng bỏ model đang cooldown
        cands = self.catalog.candidates(
            provider=tdef.provider,
            is_free=tdef.model_free,
            require_tools=req.has_tools or req.cap_config.require_tools,
            require_vision=req.cap_config.require_vision,
            min_context=req.est_tokens,
            endpoint=req.endpoint,
        )
        cands.sort(key=lambda x: (x.price_out_with_fee, -x.context_length))
        for m in cands:
            if not await self.counters.in_model_cooldown(m.id):
                return m
        return None

    def build_decision(self, key, model: ModelEntry, tier_name: str, req: ResolveRequest) -> RouteDecision:
        return RouteDecision(
            key_id=key.id, provider=key.provider, api_key=self.registry.secret(key),
            base_url=key.base_url, model_name=model.name_for(key.provider),
            model_id=model.id, tier=tier_name, endpoint=req.endpoint,
        )
