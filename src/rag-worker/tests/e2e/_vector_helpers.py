from __future__ import annotations

from typing import Any


def all_payloads(engine: Any) -> list[dict]:
    provider = engine.vectors.provider
    client = getattr(provider, "_client", None)
    if client is None:
        raise AssertionError("test helper only supports providers exposing an in-process Qdrant client")
    result = client.scroll(
        collection_name=engine.vectors.config.index_id(),
        with_payload=True,
        with_vectors=False,
        limit=10000,
    )
    points = result[0] if isinstance(result, tuple) else result
    return [dict(point.payload or {}) for point in points]


def payloads_for_document(engine: Any, document_id: str) -> list[dict]:
    return [
        payload
        for payload in all_payloads(engine)
        if payload.get("document_id") == document_id
    ]
