"""SearchUseCase — embed query + vectorstore.search + map -> candidate.

Dùng fake embedder + fake vectorstore (offline, không cần Qdrant/AI thật) để chốt:
  - embed query đi qua embedder rồi truyền đúng query_vector/query_text/top_k/document_ids
    xuống vectorstore.search.
  - SearchHit -> SearchCandidate map đúng field (kể cả page_number None).
  - ACL rỗng/None được CHUYỂN NGUYÊN xuống vectorstore (use-case không tự diễn giải).
"""

from __future__ import annotations

import pytest

from app.application.use_cases.search import SearchCandidate, SearchUseCase
from core_engine.vectorstore.types import SearchHit


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return [0.1, 0.2, 0.3]

    async def embed_batch(self, texts):  # pragma: no cover - không dùng ở search
        return [await self.embed(t) for t in texts]


class FakeVectorStore:
    def __init__(self, hits: list[SearchHit]) -> None:
        self._hits = hits
        self.search_kwargs: dict | None = None

    async def search(self, *, query_vector, query_text, top_k, document_ids):
        self.search_kwargs = {
            "query_vector": query_vector,
            "query_text": query_text,
            "top_k": top_k,
            "document_ids": document_ids,
        }
        return self._hits


def _hit() -> SearchHit:
    return SearchHit(
        chunk_id="c1",
        document_id="d1",
        document_name="Doc",
        caption="cap",
        child_text="child",
        parent_text="parent",
        heading_path=["H1"],
        score=0.9,
        page_number=None,
        source_gcs_uri="gs://s",
        markdown_gcs_uri="gs://m",
    )


async def test_search_embeds_query_and_forwards_to_vectorstore() -> None:
    embedder = FakeEmbedder()
    store = FakeVectorStore([_hit()])
    use_case = SearchUseCase(embedder, store)

    result = await use_case.search(query="câu hỏi", document_ids=["d1"], top_k=7)

    assert embedder.calls == ["câu hỏi"]
    assert store.search_kwargs == {
        "query_vector": [0.1, 0.2, 0.3],
        "query_text": "câu hỏi",
        "top_k": 7,
        "document_ids": ["d1"],
    }
    assert len(result) == 1
    candidate = result[0]
    assert isinstance(candidate, SearchCandidate)
    assert candidate.chunk_id == "c1"
    assert candidate.caption == "cap"
    assert candidate.page_number is None
    assert candidate.source_gcs_uri == "gs://s"
    assert candidate.markdown_gcs_uri == "gs://m"
    assert candidate.heading_path == ["H1"]


async def test_search_default_top_k_is_20() -> None:
    store = FakeVectorStore([])
    use_case = SearchUseCase(FakeEmbedder(), store)

    await use_case.search(query="q", document_ids=["d1"])

    assert store.search_kwargs["top_k"] == 20


@pytest.mark.parametrize("document_ids", [None, []])
async def test_search_forwards_empty_acl_unchanged(document_ids) -> None:
    # Use-case KHÔNG tự diễn giải rỗng -> chuyển nguyên xuống vectorstore (ACL ở đó).
    store = FakeVectorStore([])
    use_case = SearchUseCase(FakeEmbedder(), store)

    result = await use_case.search(query="q", document_ids=document_ids, top_k=5)

    assert result == []
    assert store.search_kwargs["document_ids"] == document_ids
