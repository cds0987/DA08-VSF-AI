import logging

import pytest

from core_engine.caption.captioner import ProviderCaptioner
from core_engine.config import HaystackSettings
from core_engine.engine import HaystackRagEngine, IngestInput


class LoggingEmbedder:
    async def embed(self, text: str):
        return [0.1]

    async def embed_batch(self, texts):
        return [[0.1] for _ in texts]


class LoggingVectors:
    async def upsert_many(self, records):
        return None

    async def list_chunk_ids_by_document(self, document_id):
        return []

    async def delete_many(self, chunk_ids):
        return None

    async def delete_by_document(self, document_id):
        return None


class FailingProvider:
    name = "offline"

    async def chat(self, *args, **kwargs):
        raise RuntimeError("provider failed")


@pytest.mark.asyncio
async def test_engine_emits_structured_ingest_logs(caplog: pytest.LogCaptureFixture) -> None:
    engine = HaystackRagEngine(
        settings=HaystackSettings(
            embed_dimension=1,
            parent_max_words=100,
            child_max_words=100,
            child_overlap_words=0,
        ),
        embedder=LoggingEmbedder(),
        vectors=LoggingVectors(),
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

    events = {record.event: record for record in caplog.records if hasattr(record, "event")}
    assert events["ingest_started"].document_id == "doc-log"
    assert events["ingest_started"].correlation_id
    assert events["ingest_completed"].correlation_id == events["ingest_started"].correlation_id
    assert events["ingest_completed"].chunk_count >= 1


@pytest.mark.asyncio
async def test_caption_fallback_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)

    caption = await ProviderCaptioner(FailingProvider()).caption("hello world")

    assert caption == "hello world"
    events = [record.event for record in caplog.records if hasattr(record, "event")]
    assert "caption_fallback" in events
