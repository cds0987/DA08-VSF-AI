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


class _ExplodingProvider:
    @staticmethod
    def cap(capability: str):
        raise RuntimeError(f"{capability} provider metadata down")


class _ExplodingModelEmbedder(_StubEmbedder):
    def __init__(self) -> None:
        self._provider = _ExplodingProvider()


class _ExplodingModelCaptioner(_StubCaptioner):
    def __init__(self) -> None:
        self._provider = _ExplodingProvider()


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


@pytest.mark.asyncio
async def test_engine_survives_model_metadata_lookup_failure() -> None:
    tracer = _RecordingTracer()
    engine = HaystackRagEngine(
        settings=HaystackSettings(
            embed_dimension=3,
            parent_max_words=100,
            child_max_words=4,
            child_overlap_words=1,
        ),
        embedder=_ExplodingModelEmbedder(),
        vectors=_StubVectors(),
        captioner=_ExplodingModelCaptioner(),
        tracer=tracer,
    )

    chunk_count = await engine.ingest(
        IngestInput(
            document_id="doc-trace-safe-model",
            document_name="Doc",
            file_type="md",
            markdown="# Title\none two three four five six seven eight",
            trace_handle=object(),
        )
    )

    assert chunk_count > 0
    assert "gen:caption" in tracer.events
    assert "gen:embed" in tracer.events


# ── Failure-matrix: mỗi stage lỗi PHẢI sinh span_error đúng stage + raise lên trên ──
# Mục tiêu: lỗi 1 stage KHÔNG được "lọt" (CI vẫn xanh) khi vào production. Mock các
# "service" ngoài (chunker/captioner/embedder/vectors) nhưng giữ ĐÚNG luồng data.

class _BoomChunker:
    def split(self, markdown):
        raise RuntimeError("chunk boom")


class _BoomCaptioner(_StubCaptioner):
    async def caption_with_metadata(self, text: str):
        raise RuntimeError("caption boom")


class _BoomEmbedder(_StubEmbedder):
    async def embed_batch(self, texts: list[str]):
        raise RuntimeError("embed boom")


class _BoomVectors(_StubVectors):
    async def upsert_many(self, records):
        raise RuntimeError("qdrant boom")


def _engine_with(*, embedder=None, vectors=None, captioner=None, chunker=None, tracer=None):
    return HaystackRagEngine(
        settings=HaystackSettings(
            embed_dimension=3,
            parent_max_words=100,
            child_max_words=4,
            child_overlap_words=1,
        ),
        embedder=embedder or _StubEmbedder(),
        vectors=vectors or _StubVectors(),
        captioner=captioner if captioner is not None else _StubCaptioner(),
        chunker=chunker,
        tracer=tracer,
    )


@pytest.mark.parametrize(
    ("stage", "kwargs"),
    [
        ("chunk", {"chunker": _BoomChunker()}),
        ("caption", {"captioner": _BoomCaptioner()}),
        ("embed", {"embedder": _BoomEmbedder()}),
        ("qdrant-write", {"vectors": _BoomVectors()}),
    ],
)
@pytest.mark.asyncio
async def test_engine_stage_failure_marks_span_error_and_reraises(stage, kwargs) -> None:
    tracer = _RecordingTracer()
    engine = _engine_with(tracer=tracer, **kwargs)

    with pytest.raises(Exception):
        await engine.ingest(
            IngestInput(
                document_id=f"doc-fail-{stage}",
                document_name="Doc",
                file_type="md",
                markdown="# Title\none two three four five six seven eight",
                trace_handle=object(),
            )
        )

    # span_error PHẢI bắn đúng stage lỗi (đây là cái cho biết "crash ở đâu")
    assert f"error:{stage}" in tracer.events
    # không stage NÀO sau stage lỗi được đóng OK (luồng dừng đúng chỗ)
    assert f"ok:{stage}" not in tracer.events
