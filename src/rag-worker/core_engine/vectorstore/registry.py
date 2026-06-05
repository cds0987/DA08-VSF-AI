"""Registry — resolve VectorDB interface theo (provider + deployment) config.

Kiến trúc provider-first (xem sơ đồ):

    Application → VectorDB Interface (search/insert/update/delete)
                 → Registry (provider + deployment config) → Provider impl
                    (qdrant · chromadb · milvus), mỗi provider tự quyết deployment
                    mode `in_process` | `remote` bên trong.

Port `VectorRepository` (app/domain, async) là interface "ra ngoài" — THỐNG NHẤT
cho mọi component dù provider là gì. `VectorStoreConfig` là config object duy nhất
Application truyền vào; Registry chỉ nhìn `config.provider` để chọn package provider.
Bên trong, `build()` của provider route deployment theo `config.url`: có url →
`remote.py` (async thuần); ko url → `inprocess.py` (embedded, async qua to_thread).

    from core_engine.vectorstore import build_vector_store, VectorStoreConfig
    store = build_vector_store(VectorStoreConfig(provider="qdrant",
                                                 url="http://localhost:6333"))  # url -> remote
    store = build_vector_store()   # VectorStoreConfig.from_env(); ko url -> in_process

Mở rộng (MOSA — bên thứ ba cắm provider mới không sửa core):

    register_backend("weaviate", lambda c: MyWeaviateRepository(c))   # đặt impl ở providers/

Factory đăng ký LAZY (import bên trong) để không kéo dependency nặng khi provider đó
không dùng (vd qdrant-client/pymilvus/chromadb chỉ cần khi chọn đúng provider).
"""

from __future__ import annotations

from typing import Callable, List

from core_engine.registry import Registry
from core_engine.vectorstore.config import VectorStoreConfig
from core_engine.vectorstore.provider import VectorStoreProvider
from core_engine.vectorstore.store import VectorStore

VectorStoreFactory = Callable[[VectorStoreConfig], VectorStore | VectorStoreProvider]

# Cùng primitive với chunker/captioner/reranker (mapping) + parser (composition).
_PROVIDERS: Registry[VectorStoreFactory] = Registry(
    "provider", entry_point_group="rag_worker.vector_store"
)


def register_backend(
    name: str, factory: VectorStoreFactory, *, override: bool = False
) -> None:
    """Dang ky provider. Trung ten ma khong `override=True` -> raise."""
    _PROVIDERS.register(name, factory, override=override)


# Alias tên theo trục mới; `register_backend` giữ lại cho caller cũ (MOSA).
register_provider = register_backend


def available_backends() -> List[str]:
    return _PROVIDERS.available()


# Alias tên theo trục mới.
available_providers = available_backends


def build_vector_store(config: VectorStoreConfig | None = None) -> VectorStore:
    """Dung VectorStore theo `config.provider`; deployment do provider tu xu ly."""
    config = config or VectorStoreConfig.from_env()
    factory = _PROVIDERS.get(config.provider)
    built = factory(config)
    if isinstance(built, VectorStore):
        return built
    if isinstance(built, VectorStoreProvider):
        return VectorStore(built, built.config)
    raise TypeError(
        f"Factory cho provider={config.provider!r} phai tra VectorStore hoac VectorStoreProvider, "
        f"nhan {type(built).__name__}"
    )


def build_vector_repository(config: VectorStoreConfig | None = None) -> VectorStore:
    """Backward-compatible alias cho callers cũ."""
    return build_vector_store(config)


# --- built-in providers (lazy import) -------------------------------------- #
# Mỗi provider là MỘT package; `build(config)` route deployment theo config.url
# (có url → remote/async thuần; ko url → in_process/to_thread). Import LAZY để chỉ
# kéo đúng provider + đúng file deployment được chọn.
def _qdrant(c: VectorStoreConfig) -> VectorStore:
    from core_engine.vectorstore.providers.qdrant import build
    return build(c)


def _chromadb(c: VectorStoreConfig) -> VectorStore:
    from core_engine.vectorstore.providers.chromadb import build
    return build(c)


def _milvus(c: VectorStoreConfig) -> VectorStore:
    from core_engine.vectorstore.providers.milvus import build
    return build(c)


register_backend("qdrant", _qdrant)
register_backend("chromadb", _chromadb)
register_backend("milvus", _milvus)
