"""Provider `qdrant` — router chọn deployment theo `config.url`.

- có url  → `remote.py`   (service riêng, AsyncQdrantClient, async thuần)
- ko url  → `inprocess.py`(embedded QdrantClient `:memory:`/path, sync + to_thread)

Import LAZY trong `build()` để chỉ kéo đúng file deployment được chọn.
"""

from __future__ import annotations

from haystack_interface.vectorstore.config import VectorStoreConfig
from haystack_interface.vectorstore.store import VectorStore


def build(config: VectorStoreConfig) -> VectorStore:
    if config.url:
        from haystack_interface.vectorstore.providers.qdrant.remote import (
            QdrantRemoteRepository,
        )
        return QdrantRemoteRepository(config)
    from haystack_interface.vectorstore.providers.qdrant.inprocess import (
        QdrantInProcessRepository,
    )
    return QdrantInProcessRepository(config)
