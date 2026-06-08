"""VectorStoreConfig for provider-first vector backends."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field, replace
from typing import Any, Mapping
from urllib.parse import urlparse, urlunparse

from core_engine.contract import ResolvedVectorstoreContract, index_id, resolve_vectorstore_contract

DEFAULT_PROVIDER = "qdrant"
DEFAULT_COLLECTION = "rag_chatbot"
DEFAULT_EMBED_MODEL = "text-embedding-3-small"
DEFAULT_REMOTE_TIMEOUT = 30


def _env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def basic_auth_header(creds: str) -> str:
    """`user:pass` -> giá trị header `Authorization: Basic <b64>`. Rỗng -> ''.

    Dùng khi Qdrant đứng sau reverse proxy (nginx) yêu cầu HTTP Basic Auth thay vì
    Qdrant api-key. qdrant-client gửi qua param `headers`."""
    creds = (creds or "").strip()
    if not creds or ":" not in creds:
        return ""
    return "Basic " + base64.b64encode(creds.encode()).decode()


def normalize_remote_qdrant_url(url: str) -> str:
    """Qdrant Cloud Run expose HTTPS qua 443; URL https thiếu port -> qdrant-client
    mặc định rớt về :6333 -> ConnectTimeout. Chèn :443 cho URL https không port
    (idempotent); http self-hosted có port giữ nguyên."""
    if not url:
        return url
    parsed = urlparse(url)
    if not parsed.scheme or parsed.port is not None or not parsed.hostname:
        return url
    if parsed.scheme == "https":
        return urlunparse(parsed._replace(netloc=f"{parsed.hostname}:443"))
    return url


@dataclass(frozen=True)
class VectorStoreConfig:
    provider: str = DEFAULT_PROVIDER
    collection: str = DEFAULT_COLLECTION
    embed_model: str = DEFAULT_EMBED_MODEL
    dimension: int = 1536
    url: str = ""
    api_key: str = ""
    basic_auth: str = ""
    options: Mapping[str, Any] = field(default_factory=dict)

    @property
    def deployment(self) -> str:
        return "remote" if self.url else "in_process"

    @property
    def backend(self) -> str:
        return self.provider

    @property
    def mode(self) -> str:
        return self.deployment

    def index_id(self) -> str:
        return index_id(self.collection, self.embed_model, self.dimension)

    def remote_client_kwargs(self) -> dict[str, Any]:
        """kwargs cho AsyncQdrantClient/QdrantClient remote: URL chuẩn hoá port 443
        + timeout nới (env QDRANT_TIMEOUT) cho Cloud Run cold start, gộp options.
        Mọi nơi dựng remote client PHẢI dùng cái này để tránh lệch cấu hình."""
        kwargs: dict[str, Any] = dict(self.options)
        kwargs.setdefault(
            "timeout", int(os.getenv("QDRANT_TIMEOUT", str(DEFAULT_REMOTE_TIMEOUT)))
        )
        header = basic_auth_header(self.basic_auth)
        if header:
            headers = dict(kwargs.get("headers") or {})
            headers.setdefault("Authorization", header)
            kwargs["headers"] = headers
        return {
            "url": normalize_remote_qdrant_url(self.url) or None,
            "api_key": self.api_key or None,
            **kwargs,
        }

    def contract(self) -> ResolvedVectorstoreContract:
        return resolve_vectorstore_contract(
            provider=self.provider,
            collection=self.collection,
            embed_model=self.embed_model,
            dimension=self.dimension,
        )

    def with_dimension(self, dimension: int) -> "VectorStoreConfig":
        if dimension == self.dimension:
            return self
        return replace(self, dimension=dimension)

    def with_embed_model(self, embed_model: str) -> "VectorStoreConfig":
        if embed_model == self.embed_model:
            return self
        return replace(self, embed_model=embed_model)

    @classmethod
    def from_env(
        cls,
        *,
        model: str | None = None,
        dimension: int | None = None,
    ) -> "VectorStoreConfig":
        provider_mode = os.getenv("AI_PROVIDER", "auto").strip().lower()
        has_real_provider = bool(_env("EMBED_API_KEY", "OPENAI_API_KEY") or _env("EMBED_BASE_URL"))
        resolved_model = model or (
            "offline"
            if provider_mode == "offline" or (provider_mode == "auto" and not has_real_provider)
            else os.getenv("EMBED_MODEL", DEFAULT_EMBED_MODEL)
        )
        contract = resolve_vectorstore_contract(
            provider=os.getenv(
                "VECTOR_DB_PROVIDER",
                os.getenv("VECTOR_PROVIDER", os.getenv("VECTOR_BACKEND", DEFAULT_PROVIDER)),
            ),
            collection=os.getenv(
                "VECTOR_COLLECTION",
                os.getenv("QDRANT_COLLECTION", DEFAULT_COLLECTION),
            ),
            embed_model=resolved_model,
            dimension=dimension,
        )
        return cls(
            provider=contract.provider,
            collection=contract.collection,
            embed_model=contract.embed_model,
            dimension=contract.dimension,
            url=os.getenv("VECTOR_DB_URL", os.getenv("QDRANT_URL", "")),
            api_key=os.getenv("VECTOR_DB_API_KEY", os.getenv("QDRANT_API_KEY", "")),
            basic_auth=os.getenv("VECTOR_DB_BASIC_AUTH", os.getenv("QDRANT_BASIC_AUTH", "")),
        )
