"""Provider `milvus` — router chọn deployment theo `config.url`.

- có url  → `remote.py`   (Milvus server/cluster, AsyncMilvusClient, async thuần)
- ko url  → `inprocess.py`(Milvus Lite, MilvusClient, sync + to_thread)

Import LAZY trong `build()` để chỉ kéo đúng file deployment được chọn.
"""

from __future__ import annotations

from haystack_interface.vectorstore.config import VectorStoreConfig
from haystack_interface.vectorstore.store import VectorStore


def build(config: VectorStoreConfig) -> VectorStore:
    if config.url:
        from haystack_interface.vectorstore.providers.milvus.remote import (
            MilvusRemoteRepository,
        )
        return MilvusRemoteRepository(config)
    from haystack_interface.vectorstore.providers.milvus.inprocess import (
        MilvusInProcessRepository,
    )
    return MilvusInProcessRepository(config)
