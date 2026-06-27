from __future__ import annotations

import os
import time
from collections import deque

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse

from app.interfaces.api.routers import ingest, search
from app.interfaces.api.runtime import compute_health, lifespan

_HEALTH_PATHS = frozenset({"/livez", "/readyz", "/health", "/healthz", "/metrics"})
_BODYLESS_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _max_request_body_bytes() -> int:
    return int(os.getenv("MAX_REQUEST_BODY_BYTES", str(2 * 1024 * 1024)))


def _rate_limit_requests() -> int:
    return int(os.getenv("RATE_LIMIT_REQUESTS", "60"))


def _rate_limit_window_seconds() -> int:
    return int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))


def _should_bypass_edge_guards(path: str) -> bool:
    return path in _HEALTH_PATHS


# rag-worker phục vụ INTERNAL RPC: mcp -> POST /api/search, document-service/NATS -> /api/ingest,
# qua mạng compose. MỌI call đến từ ÍT IP nội bộ (vd mcp 1 IP) -> rate-limit PER-IP (edge-guard
# chống abuse EXTERNAL) bóp NHẦM toàn bộ search còn RATE_LIMIT_REQUESTS/WINDOW (~1/giây) -> 429 ->
# retrieval fail -> chat trả rỗng. rag-worker KHÔNG expose ra ngoài nên KHÔNG có edge để bảo vệ
# -> miễn rate-limit per-IP cho path RPC nội bộ. VẪN giữ body-size guard (413) cho mọi path.
_INTERNAL_RPC_PREFIXES = ("/api/search", "/api/ingest")


def _is_internal_rpc_path(path: str) -> bool:
    return path.startswith(_INTERNAL_RPC_PREFIXES)


def _request_can_include_body(request: Request) -> bool:
    return request.method.upper() not in _BODYLESS_METHODS


def create_app() -> FastAPI:
    app = FastAPI(title="RAG Service", lifespan=lifespan)
    app.include_router(ingest.router, prefix="/api", tags=["ingest"])
    app.include_router(search.router, prefix="/api", tags=["search"])
    app.state.rate_limits = {}

    @app.middleware("http")
    async def apply_edge_guards(request: Request, call_next):
        if _should_bypass_edge_guards(request.url.path):
            return await call_next(request)

        # Rate-limit per-IP CHỈ cho path EXTERNAL-facing; bỏ qua RPC nội bộ (search/ingest)
        # vì mọi call từ ít IP nội bộ sẽ bị bóp nhầm -> 429 chat (xem _is_internal_rpc_path).
        if not _is_internal_rpc_path(request.url.path):
            limit = _rate_limit_requests()
            window_seconds = _rate_limit_window_seconds()
            client_ip = request.client.host if request.client else "unknown"
            now = time.monotonic()
            bucket = app.state.rate_limits.get(client_ip)
            if bucket is None:
                bucket = deque()
                app.state.rate_limits[client_ip] = bucket
            while bucket and now - bucket[0] > window_seconds:
                bucket.popleft()
            if not bucket:
                app.state.rate_limits.pop(client_ip, None)
            if len(bucket) >= limit:
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": "rate limit exceeded"},
                )
            bucket.append(now)
            app.state.rate_limits[client_ip] = bucket

        max_body = _max_request_body_bytes()
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                announced_size = int(content_length)
            except ValueError:
                announced_size = max_body + 1
            if announced_size > max_body:
                return JSONResponse(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content={"detail": "request body too large"},
                )
        if not _request_can_include_body(request):
            return await call_next(request)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > max_body:
                return JSONResponse(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content={"detail": "request body too large"},
                )
        request._body = bytes(body)
        return await call_next(request)

    @app.get("/livez")
    async def liveness():
        return {"status": "alive"}

    @app.get("/readyz")
    async def readiness():
        report = await compute_health(app.state.runtime)
        status_code = 200 if report.status == "healthy" else 503
        return JSONResponse(status_code=status_code, content=report.to_dict())

    @app.get("/health")
    async def healthcheck():
        report = await compute_health(app.state.runtime)
        status_code = 200 if report.status == "healthy" else 503
        return JSONResponse(status_code=status_code, content=report.to_dict())

    @app.get("/healthz")
    async def healthz():
        report = await compute_health(app.state.runtime)
        status_code = 200 if report.status == "healthy" else 503
        return JSONResponse(status_code=status_code, content=report.to_dict())

    @app.get("/metrics")
    async def metrics():
        report = await compute_health(app.state.runtime)
        lines = []
        for key, value in sorted(report.metrics.items()):
            metric = f"rag_worker_{key}"
            lines.append(f"# TYPE {metric} gauge")
            lines.append(f"{metric} {float(value)}")
        lines.append(f'rag_worker_healthy {1.0 if report.status == "healthy" else 0.0}')
        return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")

    return app


app = create_app()
