from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from core_engine.contract import build_contract_stamp, meta_collection_name
from core_engine.vectorstore.config import VectorStoreConfig
from core_engine.vectorstore.providers.qdrant.base import point_id


async def write_contract_stamp(
    vector_config: VectorStoreConfig,
    *,
    written_by: str,
) -> None:
    if vector_config.provider.lower() != "qdrant":
        return

    from qdrant_client import AsyncQdrantClient, QdrantClient, models

    contract = vector_config.contract()
    payload = build_contract_stamp(contract)
    payload["written_by"] = written_by
    payload["written_at"] = datetime.now(UTC).isoformat()
    collection_name = meta_collection_name(vector_config.collection)
    point = models.PointStruct(
        id=point_id(f"__contract__::{contract.index_id}"),
        vector=[1.0],
        payload=payload,
    )
    vectors_config = models.VectorParams(size=1, distance=models.Distance.COSINE)

    if vector_config.deployment == "remote":
        client = AsyncQdrantClient(
            url=vector_config.url or None,
            api_key=vector_config.api_key or None,
            **dict(vector_config.options),
        )
        if not await client.collection_exists(collection_name):
            await client.create_collection(
                collection_name=collection_name,
                vectors_config=vectors_config,
            )
        await client.upsert(collection_name=collection_name, points=[point])
        await client.close()
        return

    options = dict(vector_config.options)
    if "location" not in options and "path" not in options:
        options["location"] = ":memory:"
    client = QdrantClient(**options)

    def _write() -> None:
        if not client.collection_exists(collection_name):
            client.create_collection(
                collection_name=collection_name,
                vectors_config=vectors_config,
            )
        client.upsert(collection_name=collection_name, points=[point])
        close = getattr(client, "close", None)
        if callable(close):
            close()

    await asyncio.to_thread(_write)
