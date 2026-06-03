"""VectorStoreConfig — config object cho kiến trúc provider-first.

Application chỉ truyền MỘT config object cho VectorDB interface. Registry resolve theo:
- `provider`: qdrant | chromadb | milvus | ...
- `deployment`: SUY RA TỪ `url` — có url ⇒ `remote` (service riêng, async thuần);
  không url ⇒ `in_process` (embedded chạy thẳng trong service, async qua to_thread).

Mỗi provider có HAI file implement cho hai deployment đó (`remote.py` · `inprocess.py`);
router của provider chọn file theo `config.url`. Component bên ngoài không biết
implementation cụ thể.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

DEFAULT_DIM = 1024


@dataclass(frozen=True)
class VectorStoreConfig:
    provider: str = "qdrant"
    collection: str = "rag_chatbot"
    dimension: int = DEFAULT_DIM
    url: str = ""
    api_key: str = ""
    options: Mapping[str, Any] = field(default_factory=dict)

    @property
    def deployment(self) -> str:
        """`remote` khi có url (service riêng); ngược lại `in_process` (embedded)."""
        return "remote" if self.url else "in_process"

    @property
    def backend(self) -> str:
        """Backward-compatible alias cho code cũ."""
        return self.provider

    @property
    def mode(self) -> str:
        """Alias ngắn cho deployment."""
        return self.deployment

    def index_id(self) -> str:
        """Index/collection id encode dimension => đổi dimension là migration."""
        return f"{self.collection}__d{self.dimension}"

    def with_dimension(self, dimension: int) -> "VectorStoreConfig":
        if dimension == self.dimension:
            return self
        return replace(self, dimension=dimension)

    @classmethod
    def from_env(cls, *, dimension: int | None = None) -> "VectorStoreConfig":
        """Đọc env; deployment KHÔNG đọc trực tiếp — suy ra từ có/không `url`."""
        return cls(
            provider=os.getenv(
                "VECTOR_DB_PROVIDER",
                os.getenv("VECTOR_PROVIDER", os.getenv("VECTOR_BACKEND", "qdrant")),
            ),
            collection=os.getenv("VECTOR_COLLECTION", os.getenv("QDRANT_COLLECTION", "rag_chatbot")),
            dimension=dimension if dimension is not None
            else int(os.getenv("EMBED_DIMENSION", str(DEFAULT_DIM))),
            url=os.getenv("VECTOR_DB_URL", os.getenv("QDRANT_URL", "")),
            api_key=os.getenv("VECTOR_DB_API_KEY", os.getenv("QDRANT_API_KEY", "")),
        )
