"""Embed query - MCP-local implementation for offline hash and OpenAI."""

from __future__ import annotations

from typing import List, Protocol

from app.core.config import McpSettings
from app.core.text_utils import hash_embed


class QueryEmbedder(Protocol):
    async def embed(self, text: str) -> List[float]: ...


class OfflineEmbedder:
    def __init__(self, dimension: int) -> None:
        self._dim = dimension

    async def embed(self, text: str) -> List[float]:
        return hash_embed([text], self._dim)[0]


class OpenAIEmbedder:
    def __init__(self, *, model: str, dimension: int, api_key: str, base_url: str) -> None:
        self._model = model
        self._dim = dimension
        self._api_key = api_key
        self._base_url = base_url or None
        self._client = None

    def _openai_client(self):
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=self._api_key or None, base_url=self._base_url)
        return self._client

    async def aclose(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            await client.close()

    async def embed(self, text: str) -> List[float]:
        client = self._openai_client()
        response = await client.embeddings.create(model=self._model, input=text, dimensions=self._dim)
        return list(response.data[0].embedding)


def build_embedder(settings: McpSettings) -> QueryEmbedder:
    if settings.embed_model == "offline":
        return OfflineEmbedder(settings.dimension)
    return OpenAIEmbedder(
        model=settings.embed_model,
        dimension=settings.dimension,
        api_key=settings.embed_api_key or settings.api_key,
        base_url=settings.embed_base_url,
    )
