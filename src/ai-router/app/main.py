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

import json
import logging

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ai_router.config import get_settings
from ai_router.router import NoCapacityError, Router, RouterCallError, estimate_tokens

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("ai_router.app")

settings = get_settings()
router = Router(settings)
app = FastAPI(title="AI Router", version="0.1.0")


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


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "keys": len(router.registry.all_keys()),
            "models": len(router.catalog), "selector": router.table.selector.impl}


@app.get("/admin/quota", dependencies=[Depends(require_auth)])
async def admin_quota() -> dict:
    return await router.snapshot()


@app.post("/admin/reload", dependencies=[Depends(require_auth)])
async def admin_reload() -> dict:
    router.reload()
    return {"status": "reloaded", "routing_version": router.table.version}


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


@app.post("/v1/chat/completions")
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
        return JSONResponse(await router.embeddings(body))
    except NoCapacityError:
        raise HTTPException(status_code=503, detail="no capacity for embed")
    except RouterCallError as exc:
        raise HTTPException(status_code=502, detail=f"upstream error: {exc}")
