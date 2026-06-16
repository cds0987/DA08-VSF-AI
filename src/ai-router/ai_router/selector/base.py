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
                 tier_defs: dict[str, TierDef], params: dict | None = None) -> None:
        self.registry = registry
        self.catalog = catalog
        self.counters = counters
        self.tier_defs = tier_defs
        self.params = params or {}

    @abstractmethod
    async def resolve(self, req: ResolveRequest) -> RouteDecision | None:
        """Trả (key,base_url,model) hoặc None nếu cạn mọi tier khả thi."""

    # ----- helpers dùng chung -----
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
