import logging

import pytest

from app.domain.repositories.vector_repository import SearchLineage, SearchResult
from haystack_interface.caption.captioner import ProviderCaptioner
from haystack_interface.config import HaystackSettings
from haystack_interface.engine import HaystackRagEngine, IngestInput
from haystack_interface.rerank.llm import LLMReranker


class LoggingEmbedder:
    async def embed(self, text: str):
        return [0.1]

    async def embed_batch(self, texts):
        return [[0.1] for _ in texts]


class LoggingVectors:
    async def upsert(self, chunk_id, vector, payload):
        raise AssertionError("unexpected single upsert")

    async def upsert_many(self, records):
        return None

    async def hybrid_search(self, vector, query_text, top_k=20):
        return [
            SearchResult(
                unit_id="doc-log::p0::c0",
                document_id="doc-log",
                display_name="Doc Log",
                caption="caption",
                content="content",
                heading_path=["Title"],
                lineage=SearchLineage(
                    source_uri="local://doc-log",
                    artifact_uri="local://doc-log#artifact",
                ),
                score=0.8,
                rerank_score=0.8,
            )
        ]

    async def list_chunk_ids_by_document(self, document_id):
        return []

    async def delete_many(self, chunk_ids):
        return None

    async def delete_by_document(self, document_id):
        return None


class LoggingReranker:
    async def rerank(self, query, results, top_k, threshold):
        return results[:top_k]


class FailingProvider:
    name = "offline"

    async def chat(self, *args, **kwargs):
        raise RuntimeError("provider failed")


@pytest.mark.asyncio
async def test_engine_emits_structured_ingest_and_search_logs(caplog: pytest.LogCaptureFixture) -> None:
    engine = HaystackRagEngine(
        settings=HaystackSettings(
            embed_dimension=1,
            parent_max_words=100,
            child_max_words=100,
            child_overlap_words=0,
        ),
        embedder=LoggingEmbedder(),
        vectors=LoggingVectors(),
        reranker=LoggingReranker(),
        captioner=None,
    )

    caplog.set_level(logging.INFO)

    await engine.ingest(
        IngestInput(
            document_id="doc-log",
            document_name="Doc Log",
            file_type="md",
            markdown="# Title\nbody\n",
        )
    )
    await engine.search("query", correlation_id="cid-log", rerank_threshold=0.0)

    events = {record.event: record for record in caplog.records if hasattr(record, "event")}
    assert events["ingest_started"].document_id == "doc-log"
    assert events["ingest_completed"].chunk_count >= 1
    assert events["search_started"].correlation_id == "cid-log"
    assert events["search_completed"].result_count == 1


@pytest.mark.asyncio
async def test_caption_and_rerank_fallbacks_log_warnings(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)

    caption = await ProviderCaptioner(FailingProvider()).caption("hello world")
    reranked = await LLMReranker(FailingProvider()).rerank(
        "query",
        [
            SearchResult(
                unit_id="u1",
                document_id="d1",
                display_name="Doc",
                caption="cap",
                content="body",
                heading_path=["Title"],
                lineage=SearchLineage(source_uri="s", artifact_uri="a"),
            )
        ],
        top_k=1,
        threshold=0.0,
    )

    assert caption == "hello world"
    assert reranked
    events = [record.event for record in caplog.records if hasattr(record, "event")]
    assert "caption_fallback" in events
    assert "rerank_fallback" in events
