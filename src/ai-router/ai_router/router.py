"""Router — bộ não + engine gọi (PLAN §5). Tập hợp registry·catalog·counters·selector·client.

- resolve(): tín hiệu sống -> (key, base_url, model)
- chat()/embeddings(): resolve -> gọi provider -> parse -> account, retry+cooldown khi lỗi
- snapshot(): /admin/quota
- reload(): hot-reload routing.yaml + catalog + key (PLAN §13 file hot-reload)
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

from .catalog import load_catalog
from .client_factory import ClientFactory
from .config import RoutingTable, Settings, load_routing_table
from .counters import create_counters
from .observability import Metrics
from .parser import extract_usage
from .reconcile import build_reconcilers
from .registry import TIER_DEFS, Registry
from .schemas import Provider, RouteDecision, Usage
from .selector import ResolveRequest, build_selector

logger = logging.getLogger("ai_router.router")

MAX_ATTEMPTS = 4          # số lần thử resolve khác nhau khi key lỗi/429
COOLDOWN_SECONDS = 30
DEFAULT_OUTPUT_EST = 600  # ước lượng output mặc định (token)
DRAIN_TTL_SECONDS = 86_400  # drain key tự hết hạn sau 24h (không state ẩn vĩnh viễn)


def _seconds_to_midnight_utc() -> int:
    """429 quota-exhausted: cooldown key TỚI NỬA ĐÊM UTC (quota reset theo ngày) thay vì
    30s phẳng (retry 30s lại 429 -> phí). Tối thiểu 60s để không 0."""
    now = datetime.now(timezone.utc)
    nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60, int((nxt - now).total_seconds()))


def classify_provider_error(exc: Exception) -> str:
    """Phân loại lỗi provider -> chiến lược cooldown:
      'quota' : 429 hết quota/ngày  -> cooldown key tới nửa đêm
      'rate'  : 429 rate-limit phút -> cooldown key ngắn (30s)
      'model' : lỗi khác (5xx/4xx/timeout) -> cooldown MODEL (key có thể vẫn tốt)
    Bắt theo type + message (SDK OpenAI/OpenRouter shape khác nhau)."""
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    is_429 = "ratelimit" in name or status == 429 or "429" in msg or "rate limit" in msg
    if "insufficient_quota" in msg or "exceeded your current quota" in msg or (
        is_429 and "quota" in msg
    ):
        return "quota"
    if is_429:
        return "rate"
    return "model"


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
        self.reconcilers = build_reconcilers(settings)
        self._build_selector()

    async def reconcile_usage(self) -> None:
        """Boot hook (opt-in): đọc usage thật từ provider -> log/đối chiếu (hết 'mù 0')."""
        for rec in self.reconcilers:
            try:
                await rec.reconcile(self.registry)
            except Exception as exc:  # noqa: BLE001
                logger.warning("reconcile_provider_failed provider=%s err=%s",
                               getattr(rec, "provider", "?"), str(exc)[:160])

    def _build_selector(self) -> None:
        common = dict(registry=self.registry, catalog=self.catalog,
                      counters=self.counters, tier_defs=TIER_DEFS, metrics=self.metrics)
        self.selector = build_selector(
            self.table.selector.impl, params=self.table.selector.params, **common,
        )
        # ❖ MOSA: capability có `selector` riêng -> strategy per-node (vd think=weighted_banded).
        # Không khai -> dùng selector global. Build sẵn 1 lần, resolve() tra dict.
        self._cap_selectors = {
            name: build_selector(cap.selector.impl, params=cap.selector.params, **common)
            for name, cap in self.table.capabilities.items()
            if cap.selector is not None
        }

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
        selector = self._cap_selectors.get(capability, self.selector)
        dec = await selector.resolve(req)
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
    async def account(self, dec: RouteDecision, usage: Usage, est_tokens: int) -> float | None:
        tdef = TIER_DEFS.get(dec.tier)
        cost = usage.cost_usd
        if cost is None:  # OpenAI không trả cost -> tính từ catalog (PLAN §5.7)
            cost = self.catalog.cost(dec.model_id, usage.input_tokens, usage.output_tokens)
        await self.counters.account(
            dec.key_id, daily_kind=tdef.limit_kind if tdef else "none",
            est_tokens=est_tokens, real_tokens=usage.total_tokens, cost=cost,
        )
        return cost

    async def cooldown(self, dec: RouteDecision) -> None:
        await self.counters.set_cooldown(dec.key_id, COOLDOWN_SECONDS)

    async def cooldown_model(self, dec: RouteDecision) -> None:
        """Model vừa lỗi/sập -> nghỉ ngắn để resolve kế xoay sang model interchange khác
        (cùng key, cùng tier). Không phạt key vì key có thể vẫn tốt."""
        await self.counters.set_model_cooldown(dec.model_id, COOLDOWN_SECONDS)

    # ----------------- observability: metric + trace-log per call -----------------
    def _labels(self, dec: RouteDecision, capability: str) -> dict:
        """Nhãn ỔN ĐỊNH cho dashboard (key×model×capability). secret_env = oai-3↔ENV_3."""
        key = self.registry.get(dec.key_id)
        return {
            "key_id": dec.key_id, "secret_env": key.api_key_env if key else "",
            "model": dec.model_id, "capability": capability,
            "tier": dec.tier, "provider": dec.provider.value,
        }

    def _canon_model(self, data: dict, dec: RouteDecision, capability: str,
                     *, check_drift: bool = True) -> None:
        """GOM model về CANONICAL trên response trả về client (Langfuse đọc field `model`).

        - Ghi đè `data["model"]` = dec.model_id (id router ĐÃ quyết theo routing.yaml) -> Prometheus
          (đã dùng dec.model_id) == Langfuse, hết phân mảnh gpt-5.4-mini vs gpt-5.4-mini-2026-03-17.
        - check_drift: đối chiếu snapshot provider vs catalog; lạ (unmatched) -> phát drift để biết
          catalog cần rebuild. Stream gọi nhiều chunk -> chỉ check 1 lần (tránh over-count).
        """
        served = data.get("model", "")
        if served and check_drift:
            canon, kind = self.catalog.canonicalize(served)
            if kind == "unmatched":
                self.metrics.inc("airouter_model_unmatched_total",
                                 {"model": canon, "capability": capability})
        data["model"] = dec.model_id

    def _emit_call(self, dec: RouteDecision, capability: str, usage: Usage | None,
                   *, status: str, cost: float | None) -> None:
        labels = self._labels(dec, capability)
        self.metrics.inc("airouter_calls_total", {**labels, "status": status})
        if usage is not None:
            if usage.total_tokens:
                self.metrics.inc("airouter_tokens_total", labels, float(usage.total_tokens))
            if cost:
                self.metrics.inc("airouter_cost_usd_total", labels, float(cost))

    def _trace_log(self, event: str, dec: RouteDecision | None, capability: str, *,
                   conversation_id: str | None, status: str, latency_ms: float | None = None,
                   usage: Usage | None = None, cost: float | None = None,
                   error: str | None = None) -> None:
        """1 dòng log CÓ CẤU TRÚC mỗi call -> hết 'mù log': mọi field truy vết được
        (key/model/capability/tier/tokens/cost/latency/status + conversation_id để nối
        với Langfuse trace). devops grep/LogQL theo bất kỳ field nào."""
        extra = {
            "event": event, "capability": capability, "status": status,
            "conversation_id": conversation_id or "",
        }
        if dec is not None:
            key = self.registry.get(dec.key_id)
            extra.update({
                "key_id": dec.key_id, "secret_env": key.api_key_env if key else "",
                "model": dec.model_id, "tier": dec.tier, "provider": dec.provider.value,
            })
        if latency_ms is not None:
            extra["latency_ms"] = round(latency_ms, 1)
        if usage is not None:
            extra.update({"tokens_in": usage.input_tokens, "tokens_out": usage.output_tokens,
                          "tokens_total": usage.total_tokens})
        if cost is not None:
            extra["cost_usd"] = round(cost, 6)
        if error is not None:
            extra["error"] = error[:200]
        (logger.warning if status not in ("ok",) else logger.info)("airouter_call", extra=extra)

    async def _handle_error(self, dec: RouteDecision, capability: str, exc: Exception,
                            *, conversation_id: str | None, attempt: int) -> None:
        """429-as-truth: quota -> cooldown KEY tới nửa đêm; rate -> key 30s; khác -> model 30s.
        Dù accounting có lệch (bypass/undercount), 429 thật là tín hiệu cuối -> không dồn key cạn."""
        kind = classify_provider_error(exc)
        if kind == "quota":
            await self.counters.set_cooldown(dec.key_id, _seconds_to_midnight_utc())
            self.metrics.inc("airouter_key_429_total", {"key_id": dec.key_id, "kind": "quota"})
        elif kind == "rate":
            await self.counters.set_cooldown(dec.key_id, COOLDOWN_SECONDS)
            self.metrics.inc("airouter_key_429_total", {"key_id": dec.key_id, "kind": "rate"})
        else:
            await self.cooldown_model(dec)
        self._emit_call(dec, capability, None, status=f"error_{kind}", cost=None)
        self._trace_log("call_failed", dec, capability, conversation_id=conversation_id,
                        status=f"error_{kind}", error=f"attempt={attempt} {exc}")

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
        capability = self.table.resolve_capability(capability_alias)
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
            t0 = time.monotonic()
            try:
                resp = await client.chat.completions.create(**self._prep_body(body, dec))
                data = resp.model_dump()
                usage = extract_usage(data)
                cost = await self.account(dec, usage, est)
                latency_ms = (time.monotonic() - t0) * 1000
                self._emit_call(dec, capability, usage, status="ok", cost=cost)
                self._trace_log("call_ok", dec, capability, conversation_id=conversation_id,
                                status="ok", latency_ms=latency_ms, usage=usage, cost=cost)
                served = data.get("model", "")
                self._canon_model(data, dec, capability)
                pub = dec.public(); pub["served_model"] = served
                data["_router"] = pub
                return data
            except Exception as exc:  # noqa: BLE001 — phân loại 429 quota/rate, cooldown đúng
                last_err = exc
                await self._handle_error(dec, capability, exc,
                                         conversation_id=conversation_id, attempt=attempt)
        raise RouterCallError(str(last_err) if last_err else "unknown")

    async def chat_stream(self, capability_alias: str, body: dict,
                          conversation_id: str | None = None) -> AsyncIterator[Any]:
        """Stream pass-through (agent/SSE, PLAN §6b). Account best-effort ở chunk cuối."""
        capability = self.table.resolve_capability(capability_alias)
        messages = body.get("messages")
        est = estimate_tokens(messages)
        has_tools = bool(body.get("tools"))
        # DIAG timing: tách resolve() vs time-to-first-chunk (TTFC) từ upstream để soi điểm nghẽn
        # latency (model nhanh ~2s direct nhưng xuyên router ~8-18s). Log 1 dòng/chat ra stdout.
        _t_start = time.monotonic()
        dec = await self.resolve(
            capability_alias, est_tokens=est, has_tools=has_tools,
            has_image=_has_image(messages), conversation_id=conversation_id, endpoint="chat",
        )
        _resolve_ms = (time.monotonic() - _t_start) * 1000
        if dec is None:
            raise NoCapacityError(capability_alias)
        client = self.clients.get(dec.base_url, dec.api_key)
        # Router TỰ kiểm soát cờ stream -> bỏ 'stream' client gửi để không trùng keyword
        # (client OpenAI SDK gửi stream=True trong body; create(stream=True, **body) -> TypeError).
        sb = {k: v for k, v in body.items() if k != "stream"}
        sb.setdefault("stream_options", {"include_usage": True})
        t0 = time.monotonic()
        try:
            stream = await client.chat.completions.create(stream=True, **self._prep_body(sb, dec))
            _create_ms = (time.monotonic() - t0) * 1000   # thời gian await create() (mở request)
            usage_seen: Usage | None = None
            served_first = ""
            _ttfc_ms: float | None = None                 # time-to-first-chunk từ upstream
            async for chunk in stream:
                if _ttfc_ms is None:
                    _ttfc_ms = (time.monotonic() - t0) * 1000
                    logger.info(
                        "chat_stream_timing cap=%s model=%s est_tok=%d resolve_ms=%.0f "
                        "create_ms=%.0f ttfc_ms=%.0f", capability, dec.model_name, est,
                        _resolve_ms, _create_ms, _ttfc_ms,
                    )
                data = chunk.model_dump()
                first = not served_first
                if data.get("model") and first:
                    served_first = data["model"]          # giữ snapshot provider lần đầu thấy
                if data.get("model"):
                    # drift chỉ check ở chunk model ĐẦU (tránh over-count đa-chunk)
                    self._canon_model(data, dec, capability, check_drift=first)
                if data.get("usage"):
                    usage_seen = extract_usage(data)
                    # Gắn _router vào chunk usage cuối -> client (adapter) đọc được key_id/tier
                    # để tag Langfuse per-key (stream path KHÔNG có response.model_dump tổng).
                    pub = dec.public(); pub["served_model"] = served_first
                    data["_router"] = pub
                yield data
        except Exception as exc:  # noqa: BLE001
            await self._handle_error(dec, capability, exc,
                                     conversation_id=conversation_id, attempt=0)
            raise
        cost = await self.account(dec, usage_seen, est) if usage_seen else None
        latency_ms = (time.monotonic() - t0) * 1000
        self._emit_call(dec, capability, usage_seen, status="ok", cost=cost)
        self._trace_log("call_ok", dec, capability, conversation_id=conversation_id,
                        status="ok", latency_ms=latency_ms, usage=usage_seen, cost=cost)

    async def embeddings(self, body: dict) -> dict:
        est = estimate_tokens(None, body.get("input"))
        dec = await self.resolve("embed", est_tokens=0, endpoint="embeddings")
        if dec is None:
            raise NoCapacityError("embed")
        client = self.clients.get(dec.base_url, dec.api_key)
        out = {k: v for k, v in body.items() if k != "model"}
        out["model"] = dec.model_name
        t0 = time.monotonic()
        try:
            resp = await client.embeddings.create(**out)
        except Exception as exc:  # noqa: BLE001
            await self._handle_error(dec, "embed", exc, conversation_id=None, attempt=0)
            raise
        data = resp.model_dump()
        usage = extract_usage(data)
        cost = await self.account(dec, usage, est)
        latency_ms = (time.monotonic() - t0) * 1000
        self._emit_call(dec, "embed", usage, status="ok", cost=cost)
        self._trace_log("call_ok", dec, "embed", conversation_id=None, status="ok",
                        latency_ms=latency_ms, usage=usage, cost=cost)
        served = data.get("model", "")
        self._canon_model(data, dec, "embed")
        pub = dec.public(); pub["served_model"] = served
        data["_router"] = pub
        return data

    # ----------------- control plane: drain key (HITL v1) -----------------
    async def drain_key(self, key_id: str, *, actor: str = "?", reason: str = "",
                        ttl: int = DRAIN_TTL_SECONDS) -> dict:
        """Rút 1 key khỏi vòng xoay (KHÔNG xóa, TTL tự hết hạn). Guardrail: KHÔNG drain
        key SỐNG cuối cùng của provider (tránh tự cắt capacity). Audit log đầy đủ."""
        key = self.registry.get(key_id)
        if key is None:
            return {"ok": False, "error": f"unknown key_id: {key_id}"}
        same = self.registry.keys_for_provider(key.provider)
        live = [k for k in same
                if not await self.counters.in_cooldown(k.id)
                and not await self.counters.is_drained(k.id)]
        if not await self.counters.is_drained(key_id) and len(live) <= 1:
            logger.warning("admin_drain_refused_last_key",
                           extra={"key_id": key_id, "actor": actor, "provider": key.provider.value})
            return {"ok": False, "error": "refuse: last live key of provider (guardrail)"}
        await self.counters.set_drain(key_id, ttl)
        logger.warning("admin_drain_key",
                       extra={"key_id": key_id, "actor": actor, "reason": reason[:200], "ttl": ttl})
        return {"ok": True, "key_id": key_id, "drained": True, "ttl": ttl}

    async def resume_key(self, key_id: str, *, actor: str = "?") -> dict:
        if self.registry.get(key_id) is None:
            return {"ok": False, "error": f"unknown key_id: {key_id}"}
        await self.counters.clear_drain(key_id)
        logger.warning("admin_resume_key", extra={"key_id": key_id, "actor": actor})
        return {"ok": True, "key_id": key_id, "drained": False}

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
                "drained": await self.counters.is_drained(k.id),
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
