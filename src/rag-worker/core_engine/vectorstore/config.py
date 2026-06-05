"""VectorStoreConfig for provider-first vector backends."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from core_engine.contract import ResolvedVectorstoreContract, index_id, resolve_vectorstore_contract

DEFAULT_PROVIDER = "qdrant"
DEFAULT_COLLECTION = "rag_chatbot"
DEFAULT_EMBED_MODEL = "text-embedding-3-small"


def _env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


@dataclass(frozen=True)
class VectorStoreConfig:
    provider: str = DEFAULT_PROVIDER
    collection: str = DEFAULT_COLLECTION
    embed_model: str = DEFAULT_EMBED_MODEL
    dimension: int = 1536
    url: str = ""
    api_key: str = ""
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
        )
