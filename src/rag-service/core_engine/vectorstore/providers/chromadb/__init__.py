"""Provider `chromadb` — router chọn deployment theo `config.url`.

- có url  → `remote.py`   (Chroma server, AsyncHttpClient, async thuần)
- ko url  → `inprocess.py`(Ephemeral/Persistent, sync + to_thread)

Import LAZY trong `build()` để chỉ kéo đúng file deployment được chọn.
"""

from __future__ import annotations

from core_engine.vectorstore.config import VectorStoreConfig
from core_engine.vectorstore.store import VectorStore


def build(config: VectorStoreConfig) -> VectorStore:
    if config.url:
        from core_engine.vectorstore.providers.chromadb.remote import (
            ChromaRemoteRepository,
        )
        return ChromaRemoteRepository(config)
    from core_engine.vectorstore.providers.chromadb.inprocess import (
        ChromaInProcessRepository,
    )
    return ChromaInProcessRepository(config)
