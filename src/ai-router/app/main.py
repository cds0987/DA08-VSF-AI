"""AI Router — FastAPI gateway tương thích OpenAI (PLAN §1, §3).

Service khác chỉ đổi base_url -> http://ai-router:8010/v1 và dùng OpenAI SDK như cũ.
Endpoint:
  POST /v1/chat/completions   (model = alias capability: answer/triage/ocr/...)
  POST /v1/embeddings
  POST /v1/route              (resolver: trả triple cho ai cần client động)
  GET  /health
  GET  /admin/quota           (giám sát quota/key live)
  POST /admin/reload          (hot-reload routing.yaml + catalog)
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from ai_router.config import get_settings
from ai_router.observability import render_prometheus, render_prometheus_shared
from ai_router.router import NoCapacityError, Router, RouterCallError, estimate_tokens
from ai_router.embed_coalescer import EmbedCoalescer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("ai_router.app")

settings = get_settings()
router = Router(settings)
# Demand-driven coalescing /v1/embeddings (opt-in EMBED_COALESCE_ENABLED). OFF -> passthrough.
_embed_coalescer = EmbedCoalescer(router.embeddings)
app = FastAPI(title="AI Router", version="0.1.0")


@app.on_event("startup")
async def _reconcile_on_boot() -> None:
    """Đọc usage thật provider lúc boot (opt-in) -> thuật toán không 'mù 0'."""
    if settings.reconcile_on_boot:
        await router.reconcile_usage()


async def _metrics_flush_loop() -> None:
    """Background: định kỳ flush DELTA metrics in-process -> Redis (shared) để /metrics nhất quán
    khi chạy nhiều worker/replica. Lỗi/transient -> log + tiếp tục (không sập app)."""
    interval = settings.metrics_flush_interval_seconds
    while True:
        try:
            await router.metrics_sink.flush(router.metrics)
        except Exception as exc:  # noqa: BLE001
            logger.warning("metrics_flush_failed err=%s", str(exc)[:160])
        await asyncio.sleep(interval)


@app.on_event("startup")
async def _start_metrics_flush() -> None:
    """Bật loop flush metrics nếu có Redis sink. Không Redis (dev) -> bỏ qua (render in-process)."""
    if router.metrics_sink is not None:
        asyncio.create_task(_metrics_flush_loop())


def _auth(authorization: str | None, x_internal_token: str | None) -> None:
    """Bảo vệ nội bộ. Nếu AIROUTER_INTERNAL_TOKEN không set -> bỏ qua (dev)."""
    if not settings.internal_token:
        return
    token = x_internal_token or (authorization or "").removeprefix("Bearer ").strip()
    if token != settings.internal_token:
        raise HTTPException(status_code=401, detail="invalid internal token")


def require_auth(authorization: str | None = Header(None),
                 x_internal_token: str | None = Header(None)) -> None:
    _auth(authorization, x_internal_token)


async def _safe_json(req: Request) -> dict:
    """Parse JSON body; rỗng/lỗi -> {} (drain/resume cho phép gọi không body)."""
    try:
        body = await req.json()
        return body if isinstance(body, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "keys": len(router.registry.all_keys()),
            "models": len(router.catalog), "selector": router.table.selector.impl}


@app.get("/admin/quota", dependencies=[Depends(require_auth)])
async def admin_quota() -> dict:
    return await router.snapshot()


@app.get("/metrics")
async def metrics() -> PlainTextResponse:
    """Prometheus scrape. Per-key gauge (Redis) + leading-indicator counter (fallback/resolve-fail).
    KHÔNG lộ secret (chỉ key_id/secret_env định danh). Bind 127.0.0.1 + mạng compose nội bộ."""
    snap = await router.snapshot()
    if router.metrics_sink is not None:
        # Shared: counter/hist đọc từ Redis -> tổng across mọi worker (không phân mảnh).
        text = render_prometheus_shared(snap, await router.metrics_sink.read())
    else:
        text = render_prometheus(snap, router.metrics)   # dev/single: in-process
    return PlainTextResponse(text, media_type="text/plain; version=0.0.4; charset=utf-8")


@app.post("/admin/reload", dependencies=[Depends(require_auth)])
async def admin_reload() -> dict:
    router.reload()
    return {"status": "reloaded", "routing_version": router.table.version}


@app.post("/admin/key/{key_id}/drain", dependencies=[Depends(require_auth)])
async def admin_drain_key(key_id: str, req: Request) -> JSONResponse:
    """HITL v1: rút 1 key khỏi vòng xoay (có TTL + guardrail không drain key cuối + audit).
    Body tùy chọn {actor, reason} để ghi audit ai/vì sao."""
    body = await _safe_json(req)
    result = await router.drain_key(key_id, actor=str(body.get("actor", "?")),
                                    reason=str(body.get("reason", "")))
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


@app.post("/admin/key/{key_id}/resume", dependencies=[Depends(require_auth)])
async def admin_resume_key(key_id: str, req: Request) -> JSONResponse:
    body = await _safe_json(req)
    result = await router.resume_key(key_id, actor=str(body.get("actor", "?")))
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


@app.post("/v1/route", dependencies=[Depends(require_auth)])
async def route(req: Request) -> dict:
    """Resolver: nhận {capability, est_tokens?, has_tools?, messages?} -> triple.
    KHÔNG trả api_key trừ khi gọi nội bộ tin cậy (đã qua internal token)."""
    body = await req.json()
    cap = body.get("capability") or body.get("model") or "answer"
    est = body.get("est_tokens") or estimate_tokens(body.get("messages"))
    dec = await router.resolve(
        cap, est_tokens=est, has_tools=bool(body.get("tools")),
        conversation_id=body.get("conversation_id"),
        endpoint=body.get("endpoint", "chat"),
    )
    if dec is None:
        raise HTTPException(status_code=503, detail="no capacity")
    return dec.model_dump()


@app.post("/v1/chat/completions", response_model=None)
async def chat_completions(req: Request,
                           authorization: str | None = Header(None),
                           x_internal_token: str | None = Header(None),
                           x_conversation_id: str | None = Header(None)) -> JSONResponse | StreamingResponse:
    _auth(authorization, x_internal_token)
    body = await req.json()
    alias = body.get("model", "answer")
    try:
        if body.get("stream"):
            async def gen():
                async for chunk in router.chat_stream(alias, body, x_conversation_id):
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(gen(), media_type="text/event-stream")
        data = await router.chat(alias, body, x_conversation_id)
        return JSONResponse(data)
    except NoCapacityError:
        raise HTTPException(status_code=503, detail="no capacity (all tiers exhausted)")
    except RouterCallError as exc:
        raise HTTPException(status_code=502, detail=f"upstream error: {exc}")


@app.post("/v1/embeddings")
async def embeddings(req: Request,
                     authorization: str | None = Header(None),
                     x_internal_token: str | None = Header(None)) -> JSONResponse:
    _auth(authorization, x_internal_token)
    body = await req.json()
    try:
        return JSONResponse(await _embed_coalescer.embeddings(body))
    except NoCapacityError:
        raise HTTPException(status_code=503, detail="no capacity for embed")
    except RouterCallError as exc:
        raise HTTPException(status_code=502, detail=f"upstream error: {exc}")


@app.post("/v1/rerank")
async def rerank(req: Request,
                 authorization: str | None = Header(None),
                 x_internal_token: str | None = Header(None)) -> JSONResponse:
    """Cohere /rerank passthrough (model = alias capability rerank_api). GIỮ NGUYÊN Cohere
    rerank-4-pro@OpenRouter — chuẩn hoá đi qua gateway (1 cổng + accounting/cooldown)."""
    _auth(authorization, x_internal_token)
    body = await req.json()
    try:
        return JSONResponse(await router.rerank(body))
    except NoCapacityError:
        raise HTTPException(status_code=503, detail="no capacity for rerank")
    except RouterCallError as exc:
        raise HTTPException(status_code=502, detail=f"upstream error: {exc}")
