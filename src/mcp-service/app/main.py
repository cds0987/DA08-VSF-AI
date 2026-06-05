"""Entry mcp-service. Startup FAIL-CLOSED: verify contract Qdrant trước khi serve.

Chạy: python -m app.main   (từ thư mục src/mcp-service)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from app.core.config import load_settings
from app.core.contract import VectorstoreContractError
from app.interfaces.mcp_server import MCP_DEFAULT_HOST, MCP_DEFAULT_PORT, build_mcp, mcp_endpoint_url

logger = logging.getLogger("mcp-service")


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

    # FAIL-CLOSED: contract lệch / thiếu dấu niêm -> crash, KHÔNG phục vụ search.
    try:
        asyncio.run(service.verify_contract())
    except VectorstoreContractError as exc:
        logger.error("mcp_contract_verify_failed: %s", exc)
        return 1
    logger.info("mcp_contract_verified index=%s", contract.index_id)

    mcp.run(transport="streamable-http")
    return 0


if __name__ == "__main__":
    sys.exit(main())
