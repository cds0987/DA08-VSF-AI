"""Router — bộ não + engine gọi (PLAN §5). Tập hợp registry·catalog·counters·selector·client.

- resolve(): tín hiệu sống -> (key, base_url, model)
- chat()/embeddings(): resolve -> gọi provider -> parse -> account, retry+cooldown khi lỗi
- snapshot(): /admin/quota
- reload(): hot-reload routing.yaml + catalog + key (PLAN §13 file hot-reload)
"""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from .catalog import load_catalog
from .client_factory import ClientFactory
from .config import RoutingTable, Settings, load_routing_table
from .counters import create_counters
from .observability import Metrics
from .parser import extract_usage
from .registry import TIER_DEFS, Registry
from .schemas import Provider, RouteDecision, Usage
from .selector import ResolveRequest, build_selector

logger = logging.getLogger("ai_router.router")

MAX_ATTEMPTS = 4          # số lần thử resolve khác nhau khi key lỗi/429
COOLDOWN_SECONDS = 30
DEFAULT_OUTPUT_EST = 600  # ước lượng output mặc định (token)


def estimate_tokens(messages: list[dict] | None, input_text: Any = None) -> int:
    """Ước lượng thô input+output (PLAN §5.0). ~4 ký tự/token."""
    chars = 0
    for m in messages or []:
        c = m.get("content")
        if isinstance(c, str):
            chars += len(c)
        elif isinstance(c, list):  # content parts (vision)
            for part in c:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    chars += len(part["text"])
    if isinstance(input_text, str):
        chars += len(input_text)
    return chars // 4 + DEFAULT_OUTPUT_EST


class Router:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.registry = Registry.from_env()
        self.catalog = load_catalog(settings.catalog_path)
        self.table: RoutingTable = load_routing_table(settings.routing_path)
        self.counters = create_counters(settings.redis_url)
        self.clients = ClientFactory(timeout=settings.request_timeout)
        self.metrics = Metrics()   # leading-indicator counters (fallback, resolve-fail)
        self._build_selector()

    def _build_selector(self) -> None:
        self.selector = build_selector(
            self.table.selector.impl, registry=self.registry, catalog=self.catalog,
            counters=self.counters, tier_defs=TIER_DEFS, params=self.table.selector.params,
        )

    def reload(self) -> None:
        """Hot-reload (file routing.yaml + catalog + key). Lỗi -> giữ bản cũ."""
        try:
            self.table = load_routing_table(self.settings.routing_path)
            self.catalog = load_catalog(self.settings.catalog_path)
            self.registry = Registry.from_env()
            self._build_selector()
            logger.info("reloaded routing version=%s models=%d keys=%d",
                        self.table.version, len(self.catalog), len(self.registry.all_keys()))
        except Exception as exc:  # noqa: BLE001
            logger.error("reload_failed err=%s (giữ bản cũ)", str(exc)[:200])

    # ----------------- resolve -----------------
    async def resolve(self, capability_alias: str, *, est_tokens: int, has_tools: bool = False,
                      has_image: bool = False, conversation_id: str | None = None,
                      endpoint: str = "chat") -> RouteDecision | None:
        capability = self.table.resolve_capability(capability_alias)
        cap = self.table.capabilities.get(capability)
        if cap is None:
            logger.warning("unknown_capability alias=%s", capability_alias)
            self.metrics.inc("airouter_resolve_fail_total",
                             {"capability": capability_alias, "reason": "unknown_capability"})
            return None
        req = ResolveRequest(
            capability=capability, cap_config=cap, est_tokens=est_tokens,
            has_tools=has_tools, has_image=has_image, conversation_id=conversation_id,
            endpoint=endpoint,
        )
        dec = await self.selector.resolve(req)
        if dec is None:
            self.metrics.inc("airouter_resolve_fail_total",
                             {"capability": capability, "reason": "no_capacity"})
            return None
        # LEADING INDICATOR: tier != tier ưu tiên (tiers[0]) -> đang fallback (nguy cơ drift/cost).
        self.metrics.inc("airouter_resolve_total",
                         {"capability": capability, "tier": dec.tier, "provider": dec.provider.value})
        primary = cap.tiers[0] if cap.tiers else None
        if primary is not None and dec.tier != primary:
            self.metrics.inc("airouter_fallback_total", {"capability": capability, "tier": dec.tier})
        return dec

    # ----------------- accounting -----------------
    async def account(self, dec: RouteDecision, usage: Usage, est_tokens: int) -> None:
        tdef = TIER_DEFS.get(dec.tier)
        cost = usage.cost_usd
        if cost is None:  # OpenAI không trả cost -> tính từ catalog (PLAN §5.7)
            cost = self.catalog.cost(dec.model_id, usage.input_tokens, usage.output_tokens)
        await self.counters.account(
            dec.key_id, daily_kind=tdef.limit_kind if tdef else "none",
            est_tokens=est_tokens, real_tokens=usage.total_tokens, cost=cost,
        )

    async def cooldown(self, dec: RouteDecision) -> None:
        await self.counters.set_cooldown(dec.key_id, COOLDOWN_SECONDS)

    async def cooldown_model(self, dec: RouteDecision) -> None:
        """Model vừa lỗi/sập -> nghỉ ngắn để resolve kế xoay sang model interchange khác
        (cùng key, cùng tier). Không phạt key vì key có thể vẫn tốt."""
        await self.counters.set_model_cooldown(dec.model_id, COOLDOWN_SECONDS)

    # ----------------- call engine -----------------
    def _prep_body(self, body: dict, dec: RouteDecision) -> dict:
        """Gán model thật + chuẩn hoá param theo provider (PLAN §6)."""
        out = {k: v for k, v in body.items() if k != "model"}
        out["model"] = dec.model_name
        if dec.provider == Provider.OPENAI:
            # OpenAI mới yêu cầu max_completion_tokens, không phải max_tokens
            if "max_tokens" in out and "max_completion_tokens" not in out:
                out["max_completion_tokens"] = out.pop("max_tokens")
        return out

    async def chat(self, capability_alias: str, body: dict,
                   conversation_id: str | None = None) -> dict:
        """Non-stream chat/completions. Trả response dict (OpenAI shape) + _router meta."""
        messages = body.get("messages")
        est = estimate_tokens(messages)
        has_tools = bool(body.get("tools"))
        has_image = _has_image(messages)
        last_err: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            dec = await self.resolve(
                capability_alias, est_tokens=est, has_tools=has_tools,
                has_image=has_image, conversation_id=conversation_id, endpoint="chat",
            )
            if dec is None:
                raise NoCapacityError(capability_alias)
            client = self.clients.get(dec.base_url, dec.api_key)
            try:
                resp = await client.chat.completions.create(**self._prep_body(body, dec))
                data = resp.model_dump()
                await self.account(dec, extract_usage(data), est)
                data["_router"] = dec.public()
                return data
            except Exception as exc:  # noqa: BLE001 — lỗi/sập -> cooldown model, thử model/tier khác
                last_err = exc
                await self.cooldown_model(dec)
                logger.warning("chat_attempt_failed attempt=%d key=%s model=%s err=%s",
                               attempt, dec.key_id, dec.model_id, str(exc)[:160])
        raise RouterCallError(str(last_err) if last_err else "unknown")

    async def chat_stream(self, capability_alias: str, body: dict,
                          conversation_id: str | None = None) -> AsyncIterator[Any]:
        """Stream pass-through (agent/SSE, PLAN §6b). Account best-effort ở chunk cuối."""
        messages = body.get("messages")
        est = estimate_tokens(messages)
        has_tools = bool(body.get("tools"))
        dec = await self.resolve(
            capability_alias, est_tokens=est, has_tools=has_tools,
            has_image=_has_image(messages), conversation_id=conversation_id, endpoint="chat",
        )
        if dec is None:
            raise NoCapacityError(capability_alias)
        client = self.clients.get(dec.base_url, dec.api_key)
        # Router TỰ kiểm soát cờ stream -> bỏ 'stream' client gửi để không trùng keyword
        # (client OpenAI SDK gửi stream=True trong body; create(stream=True, **body) -> TypeError).
        sb = {k: v for k, v in body.items() if k != "stream"}
        sb.setdefault("stream_options", {"include_usage": True})
        stream = await client.chat.completions.create(stream=True, **self._prep_body(sb, dec))
        usage_seen: Usage | None = None
        async for chunk in stream:
            data = chunk.model_dump()
            if data.get("usage"):
                usage_seen = extract_usage(data)
                # Gắn _router vào chunk usage cuối -> client (adapter) đọc được key_id/tier
                # để tag Langfuse per-key (stream path KHÔNG có response.model_dump tổng).
                data["_router"] = dec.public()
            yield data
        if usage_seen:
            await self.account(dec, usage_seen, est)

    async def embeddings(self, body: dict) -> dict:
        est = estimate_tokens(None, body.get("input"))
        dec = await self.resolve("embed", est_tokens=0, endpoint="embeddings")
        if dec is None:
            raise NoCapacityError("embed")
        client = self.clients.get(dec.base_url, dec.api_key)
        out = {k: v for k, v in body.items() if k != "model"}
        out["model"] = dec.model_name
        resp = await client.embeddings.create(**out)
        data = resp.model_dump()
        await self.account(dec, extract_usage(data), est)
        data["_router"] = dec.public()
        return data

    # ----------------- giám sát -----------------
    async def snapshot(self) -> dict:
        keys = []
        for k in self.registry.all_keys():
            tdef = TIER_DEFS.get(k.tier)
            u = await self.counters.usage(k.id, tdef.limit_kind if tdef else "none")
            limit = k.limit.value
            remaining = max(limit - u["daily_used"], 0) if k.limit.kind != "none" else None
            keys.append({
                "key_id": k.id, "secret_env": k.api_key_env,
                "provider": k.provider.value, "tier": k.tier,
                "limit_kind": k.limit.kind, "limit": limit,
                "used_today": u["daily_used"], "remaining": remaining,
                "rpm_now": u["rpm"], "cost_month": u["cost_month"], "cooldown": u["cooldown"],
            })
        return {"routing_version": self.table.version, "models": len(self.catalog),
                "selector": self.table.selector.impl, "keys": keys}


def _has_image(messages: list[dict] | None) -> bool:
    for m in messages or []:
        c = m.get("content")
        if isinstance(c, list):
            for part in c:
                if isinstance(part, dict) and part.get("type") in ("image_url", "input_image"):
                    return True
    return False


class NoCapacityError(Exception):
    """Cạn mọi tier khả thi (PLAN §5.3)."""


class RouterCallError(Exception):
    """Gọi provider thất bại sau MAX_ATTEMPTS."""
