from __future__ import annotations

import json
from typing import Any


async def rag_search_probe(
    mcp_url: str,
    query: str,
    document_ids: list[str],
    *,
    top_k: int = 8,
    internal_token: str | None = None,
) -> dict[str, Any]:
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        import httpx
    except ImportError as exc:
        return {"ok": False, "reason": f"mcp SDK/httpx import failed: {exc}", "results": []}

    endpoint = mcp_url.rstrip("/")
    if not endpoint.endswith("/mcp"):
        endpoint = f"{endpoint}/mcp"
    headers = {}
    if internal_token:
        headers["X-Internal-Token"] = internal_token
    try:
        async with httpx.AsyncClient(timeout=60, headers=headers) as http_client:
            async with streamable_http_client(endpoint, http_client=http_client) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "rag_search",
                        arguments={"query": query, "document_ids": document_ids, "top_k": top_k},
                    )
        payload = _result_payload(result)
        results = payload.get("results") if isinstance(payload, dict) else []
        return {"ok": True, "results": results if isinstance(results, list) else [], "raw": payload}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": str(exc), "results": []}


def _result_payload(result: Any) -> Any:
    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured
    content = getattr(result, "content", None)
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                if "json" in item:
                    return item["json"]
                text = item.get("text")
            else:
                text = getattr(item, "text", None)
            if isinstance(text, str):
                try:
                    return json.loads(text)
                except ValueError:
                    continue
    return {}

