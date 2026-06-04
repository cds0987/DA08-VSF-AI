"""vectorstore — facade async thống nhất cho nhiều vector database (provider-first).

Sơ đồ:

    Application → VectorDB Interface → Registry (provider + deployment) → Provider

- `VectorStore`: VectorDB Interface dùng chung ra ngoài (`insert/upsert/search/delete`).
- `VectorStoreConfig`: config object DUY NHẤT (provider + deployment + kết nối + dimension).
- `build_vector_store(config)`: Registry dựng facade theo `config.provider` (mặc định from_env).
- `register_backend(name, factory)`: cắm provider mới (MOSA — bên thứ ba không sửa core).
- `providers/`: qdrant · chromadb · milvus — mỗi provider tự xử lý `in_process` | `remote`.

CHỦ Ý: không export sẵn provider repo cụ thể ở đây vì mỗi provider kéo dependency
nặng riêng (qdrant-client / chromadb / pymilvus). Lấy instance qua `build_vector_store`
hoặc import trực tiếp submodule:

    from core_engine.vectorstore.providers.qdrant.remote import QdrantRemoteRepository
"""

from core_engine.vectorstore.config import VectorStoreConfig
from core_engine.vectorstore.provider import VectorStoreProvider
from core_engine.vectorstore.registry import (
    available_backends,
    available_providers,
    build_vector_store,
    build_vector_repository,
    register_backend,
    register_provider,
)
from core_engine.vectorstore.store import VectorStore
from core_engine.vectorstore.types import VectorRecord

__all__ = [
    "VectorStore",
    "VectorStoreProvider",
    "VectorRecord",
    "VectorStoreConfig",
    "build_vector_store",
    "build_vector_repository",
    "register_backend",
    "register_provider",
    "available_backends",
    "available_providers",
]
