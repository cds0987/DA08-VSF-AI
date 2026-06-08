"""Entry point for mcp-service with fail-closed tool verification."""

from __future__ import annotations

import asyncio
import logging
import sys

from app.core.config import load_settings
from app.core.contract import VectorstoreContractError
from app.interfaces.mcp_server import (
    InternalTokenAuthMiddleware,
    build_mcp,
    mcp_endpoint_url,
)

logger = logging.getLogger("mcp-service")


async def _close_tools(tools) -> None:
    for tool in tools:
        close = getattr(tool, "aclose", None)
        if callable(close):
            await close()


async def _verify_and_reset(tools) -> None:
    try:
        for tool in tools:
            verify = getattr(tool, "verify", None)
            if callable(verify):
                await verify()
    finally:
        # Drop any clients created during startup verification so the serving loop
        # can lazy-init fresh pooled clients bound to its own event loop.
        await _close_tools(tools)


def main() -> int:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    mcp, tools = build_mcp(settings)
    tool_names = [tool.name for tool in tools]

    logger.info(
        "mcp_startup tool_count=%d tools=%s",
        len(tool_names),
        ",".join(tool_names),
    )
    logger.info(
        "mcp_transport transport=streamable-http endpoint=%s",
        mcp_endpoint_url(settings.host, settings.port),
    )
    logger.info("mcp_auth mode=%s", "internal-token" if settings.auth_enabled else "disabled")

    try:
        asyncio.run(_verify_and_reset(tools))
    except VectorstoreContractError as exc:
        logger.error("mcp_contract_verify_failed: %s", exc)
        return 1
    logger.info(
        "mcp_startup_verified tool_count=%d tools=%s",
        len(tool_names),
        ",".join(tool_names),
    )

    # FastMCP.run() chỉ nhận (transport, mount_path) — không nhận middleware. Để gắn
    # auth internal-token, dựng Starlette app từ streamable_http_app() rồi add_middleware,
    # và tự serve bằng uvicorn.
    import uvicorn

    app = mcp.streamable_http_app()
    token = (settings.internal_token or "").strip()
    if token:
        app.add_middleware(InternalTokenAuthMiddleware, token=token)

    try:
        uvicorn.run(app, host=settings.host, port=settings.port,
                    log_level=settings.log_level.lower())
    finally:
        asyncio.run(_close_tools(tools))
    return 0


if __name__ == "__main__":
    sys.exit(main())
