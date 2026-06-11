from __future__ import annotations

import pytest

from core_engine.config import HaystackSettings
from core_engine.engine import HaystackRagEngine, IngestInput


class _StubEmbedder:
    def __init__(self) -> None:
        self._provider = type(
            "Provider",
            (),
            {"cap": staticmethod(lambda capability: type("Cfg", (), {"model": f"{capability}-model"})())},
        )()

    async def embed(self, text: str):
        return [0.1]

    async def embed_batch(self, texts: list[str]):
        return [[0.1] for _ in texts]


class _StubVectors:
    def __init__(self) -> None:
        self.config = type("Cfg", (), {"index_id": lambda self: "rag_chatbot__te3s__d1536"})()

    async def upsert_many(self, records):
        return None

    async def list_chunk_ids_by_document(self, document_id):
        return []

    async def delete_many(self, chunk_ids):
        return None

    async def delete_by_document(self, document_id):
        return None


class _StubCaptioner:
    def __init__(self) -> None:
        self._provider = type(
            "Provider",
            (),
            {"cap": staticmethod(lambda capability: type("Cfg", (), {"model": f"{capability}-model"})())},
        )()

    async def caption_with_metadata(self, text: str):
        return type("CaptionResult", (), {"text": f"caption:{text[:5]}", "used_fallback": False})()


class _RecordingTracer:
    def __init__(self) -> None:
        self.events: list[str] = []

    def span_start(self, trace, name, payload):
        self.events.append(f"start:{name}")
        return name

    def span_ok(self, span, payload):
        self.events.append(f"ok:{span}")

    def span_error(self, span, exc):
        self.events.append(f"error:{span}")

    def generation(self, trace, **kwargs):
        self.events.append(f"gen:{kwargs['name']}")


@pytest.mark.asyncio
async def test_engine_emits_langfuse_stages_in_order() -> None:
    tracer = _RecordingTracer()
    engine = HaystackRagEngine(
        settings=HaystackSettings(
            embed_dimension=3,
            parent_max_words=100,
            child_max_words=4,
            child_overlap_words=1,
        ),
        embedder=_StubEmbedder(),
        vectors=_StubVectors(),
        captioner=_StubCaptioner(),
        tracer=tracer,
    )

    await engine.ingest(
        IngestInput(
            document_id="doc-trace",
            document_name="Doc",
            file_type="md",
            markdown="# Title\none two three four five six seven eight",
            trace_handle=object(),
        )
    )

    assert tracer.events == [
        "start:chunk",
        "ok:chunk",
        "start:caption",
        "gen:caption",
        "ok:caption",
        "start:embed",
        "gen:embed",
        "ok:embed",
        "start:qdrant-write",
        "ok:qdrant-write",
    ]
