from __future__ import annotations

import os
from uuid import uuid4

import pytest

pytest.importorskip("qdrant_client")

from qdrant_client import AsyncQdrantClient

from haystack_interface.tests._contract import assert_vector_repository_contract
from haystack_interface.vectorstore import VectorStoreConfig
from haystack_interface.vectorstore.providers.qdrant.remote import QdrantRemoteRepository


@pytest.mark.asyncio
async def test_qdrant_remote_repository_contract() -> None:
    qdrant_url = os.getenv("QDRANT_URL") or os.getenv("VECTOR_DB_URL")
    if not qdrant_url:
        pytest.skip("set QDRANT_URL or VECTOR_DB_URL to run remote Qdrant contract test")

    qdrant_api_key = os.getenv("QDRANT_API_KEY") or os.getenv("VECTOR_DB_API_KEY") or ""
    collection = f"rag_contract_{uuid4().hex[:12]}"
    config = VectorStoreConfig(
        provider="qdrant",
        collection=collection,
        dimension=64,
        url=qdrant_url,
        api_key=qdrant_api_key,
    )

    client = AsyncQdrantClient(url=qdrant_url, api_key=qdrant_api_key or None)
    try:
        await assert_vector_repository_contract(
            lambda _cfg: QdrantRemoteRepository(config),
            dim=config.dimension,
        )
    finally:
        if await client.collection_exists(config.index_id()):
            await client.delete_collection(config.index_id())
        await client.close()
