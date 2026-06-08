from __future__ import annotations

import pytest
from qdrant_client.http.exceptions import UnexpectedResponse

pytest.importorskip("qdrant_client")

from core_engine.vectorstore.config import VectorStoreConfig
from core_engine.vectorstore.providers.qdrant import remote as remote_module
from core_engine.vectorstore.providers.qdrant.remote import QdrantRemoteProvider
from core_engine.vectorstore.types import VectorRecord


class _FakePoint:
    def __init__(self, chunk_id: str) -> None:
        self.payload = {"chunk_id": chunk_id}


class _FakeClient:
    def __init__(self, *args, **kwargs) -> None:
        self.upsert_calls: list[list[object]] = []
        self.scroll_calls: list[dict[str, object]] = []

    async def collection_exists(self, collection_name: str) -> bool:
        return True

    async def create_collection(self, **kwargs) -> None:
        return None

    async def create_payload_index(self, **kwargs) -> None:
        return None

    async def upsert(self, *, collection_name: str, points) -> None:
        self.upsert_calls.append(list(points))

    async def scroll(self, **kwargs):
        self.scroll_calls.append(dict(kwargs))
        if len(self.scroll_calls) == 1:
            return [_FakePoint("doc-1::c0")], "offset-1"
        return [_FakePoint("doc-1::c1")], None


class _MissingThenRecoverClient(_FakeClient):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.create_collection_calls = 0
        self.create_payload_index_calls = 0
        self._upsert_attempts = 0
        self._exists = True

    async def collection_exists(self, collection_name: str) -> bool:
        return self._exists

    async def create_collection(self, **kwargs) -> None:
        self.create_collection_calls += 1
        self._exists = True

    async def create_payload_index(self, **kwargs) -> None:
        self.create_payload_index_calls += 1

    async def upsert(self, *, collection_name: str, points) -> None:
        self._upsert_attempts += 1
        if self._upsert_attempts == 1:
            self._exists = False
            raise UnexpectedResponse(
                status_code=404,
                reason_phrase="Not Found",
                content=f"Collection `{collection_name}` doesn't exist!",
                headers={},
            )
        await super().upsert(collection_name=collection_name, points=points)


class _MissingForeverClient(_FakeClient):
    async def upsert(self, *, collection_name: str, points) -> None:
        raise UnexpectedResponse(
            status_code=404,
            reason_phrase="Not Found",
            content=f"Collection `{collection_name}` doesn't exist!",
            headers={},
        )


@pytest.mark.asyncio
async def test_qdrant_remote_upsert_many_batches_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPSERT_BATCH_SIZE", "2")
    monkeypatch.setattr(remote_module, "AsyncQdrantClient", _FakeClient)
    provider = QdrantRemoteProvider(
        VectorStoreConfig(provider="qdrant", collection="rag", dimension=3, url="http://qdrant")
    )

    await provider.upsert_many(
        [
            VectorRecord("a", [1.0, 0.0, 0.0], {"document_id": "doc"}),
            VectorRecord("b", [0.0, 1.0, 0.0], {"document_id": "doc"}),
            VectorRecord("c", [0.0, 0.0, 1.0], {"document_id": "doc"}),
        ]
    )

    assert len(provider._client.upsert_calls) == 2
    assert [len(batch) for batch in provider._client.upsert_calls] == [2, 1]


@pytest.mark.asyncio
async def test_qdrant_remote_lists_chunk_ids_across_scroll_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(remote_module, "AsyncQdrantClient", _FakeClient)
    provider = QdrantRemoteProvider(
        VectorStoreConfig(provider="qdrant", collection="rag", dimension=3, url="http://qdrant")
    )

    chunk_ids = await provider.list_chunk_ids_by_document("doc-1")

    assert chunk_ids == ["doc-1::c0", "doc-1::c1"]
    assert len(provider._client.scroll_calls) == 2


@pytest.mark.asyncio
async def test_qdrant_remote_recreates_collection_and_retries_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(remote_module, "AsyncQdrantClient", _MissingThenRecoverClient)
    provider = QdrantRemoteProvider(
        VectorStoreConfig(provider="qdrant", collection="rag", dimension=3, url="http://qdrant")
    )

    await provider.upsert_many([VectorRecord("a", [1.0, 0.0, 0.0], {"document_id": "doc"})])

    assert provider._client.create_collection_calls == 1
    assert provider._client.create_payload_index_calls == 1
    assert len(provider._client.upsert_calls) == 1


@pytest.mark.asyncio
async def test_qdrant_remote_raises_when_collection_missing_after_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(remote_module, "AsyncQdrantClient", _MissingForeverClient)
    provider = QdrantRemoteProvider(
        VectorStoreConfig(provider="qdrant", collection="rag", dimension=3, url="http://qdrant")
    )

    with pytest.raises(UnexpectedResponse):
        await provider.upsert_many([VectorRecord("a", [1.0, 0.0, 0.0], {"document_id": "doc"})])
