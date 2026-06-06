"""Entry point for mcp-service with fail-closed contract verification."""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from app.core.config import load_settings
from app.core.contract import VectorstoreContractError
from app.interfaces.mcp_server import MCP_DEFAULT_HOST, MCP_DEFAULT_PORT, build_mcp, mcp_endpoint_url

logger = logging.getLogger("mcp-service")


async def _close_service(service) -> None:
    close = getattr(service, "aclose", None)
    if callable(close):
        await close()


async def _verify_and_reset(service) -> None:
    try:
        await service.verify_contract()
    finally:
        # Drop any clients created during startup verification so the serving loop
        # can lazy-init fresh pooled clients bound to its own event loop.
        await _close_service(service)


def main() -> int:
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = load_settings()
    contract = settings.contract()
    logger.info(
        "mcp_startup index=%s fingerprint=%s deployment=%s",
        contract.index_id,
        contract.fingerprint,
        settings.deployment,
    )
    logger.info(
        "mcp_transport transport=streamable-http endpoint=%s",
        mcp_endpoint_url(
            os.getenv("MCP_HOST", MCP_DEFAULT_HOST),
            int(os.getenv("MCP_PORT", str(MCP_DEFAULT_PORT))),
        ),
    )

    mcp, service = build_mcp(settings)

    try:
        asyncio.run(_verify_and_reset(service))
    except VectorstoreContractError as exc:
        logger.error("mcp_contract_verify_failed: %s", exc)
        return 1
    logger.info("mcp_contract_verified index=%s", contract.index_id)

    try:
        mcp.run(transport="streamable-http")
    finally:
        asyncio.run(_close_service(service))
    return 0


if __name__ == "__main__":
    sys.exit(main())
