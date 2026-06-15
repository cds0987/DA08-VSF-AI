from __future__ import annotations

import sys
import types

import pytest

from app.infrastructure.observability.ingest_tracing import CompositeIngestTracer
from app.infrastructure.observability.langsmith_tracer import (
    LangSmithIngestTracer,
    build_langsmith_ingest_tracer,
)


# ── Fake langsmith RunTree/Client (KHÔNG gọi mạng) ───────────────────────────
class _FakeClient:
    def __init__(self) -> None:
        self.events: list[str] = []

    def flush(self) -> None:
        self.events.append("flush")


class _FakeRunTree:
    def __init__(self, *, name, run_type, inputs=None, project_name=None,
                 client=None, start_time=None, extra=None) -> None:
        self._client = client
        self.name = name
        client.events.append(f"root:{name}:{project_name}")

    def post(self) -> None:
        self._client.events.append(f"post:{self.name}")

    def patch(self) -> None:
        self._client.events.append(f"patch:{self.name}")

    def end(self, **kwargs) -> None:
        self._client.events.append(f"end:{self.name}:{'ERR' if kwargs.get('error') else 'OK'}")

    def create_child(self, *, name, run_type, inputs=None, start_time=None, extra=None):
        self._client.events.append(f"child:{name}:{run_type}")
        child = _FakeRunTree.__new__(_FakeRunTree)
        child._client = self._client
        child.name = name
        return child


@pytest.fixture
def fake_runtree(monkeypatch):
    mod = types.ModuleType("langsmith.run_trees")
    mod.RunTree = _FakeRunTree
    monkeypatch.setitem(sys.modules, "langsmith.run_trees", mod)
    return _FakeRunTree


@pytest.mark.asyncio
async def test_langsmith_tracer_happy_path(fake_runtree) -> None:
    client = _FakeClient()
    tracer = LangSmithIngestTracer(client, project="vsf-rag-ingest", sample_rate=1.0)

    trace = tracer.start_job(
        "doc-1",
        {"attempt": 0, "uri": "s3://a", "mime": "png", "source_uri": "s3://a"},
    )
    span = tracer.span_start(trace, "parse", {"uri": "s3://a"})
    tracer.span_ok(span, {"chars": 10})
    await tracer.finish_job(trace, "COMPLETED", {"chunk_count": 1})

    assert "root:doc-ingest:vsf-rag-ingest" in client.events
    assert "child:parse:tool" in client.events
    assert "end:parse:OK" in client.events
    assert "end:doc-ingest:OK" in client.events
    assert "flush" in client.events


@pytest.mark.asyncio
async def test_langsmith_tracer_ci_smoke_uses_separate_project(fake_runtree) -> None:
    client = _FakeClient()
    tracer = LangSmithIngestTracer(client, project="vsf-rag-ingest", sample_rate=1.0)

    tracer.start_job("doc-2", {"attempt": 0, "correlation_id": "nats:ci-smoke:doc-2"})

    assert "root:doc-ingest:vsf-rag-ingest-ci-smoke" in client.events


@pytest.mark.asyncio
async def test_langsmith_tracer_error_promotes_when_unsampled(fake_runtree) -> None:
    client = _FakeClient()
    tracer = LangSmithIngestTracer(client, project="p", sample_rate=0.0, trace_on_error=True)

    trace = tracer.start_job("doc-3", {"attempt": 0, "uri": "s3://a"})
    span = tracer.span_start(trace, "embed", {"chunks": 3})
    tracer.span_error(span, RuntimeError("boom"))
    await tracer.finish_job(trace, "FAILED", {"stage": "embed"})

    # Chưa sample nhưng lỗi -> root + child được tạo để thấy điểm hỏng.
    assert "root:doc-ingest:p" in client.events
    assert "child:embed:tool" in client.events
    assert "end:embed:ERR" in client.events
    assert "end:doc-ingest:OK" in client.events  # finish ghi status trong outputs


def test_build_langsmith_tracer_none_when_disabled() -> None:
    settings = type("S", (), {"langsmith_enabled": False, "langsmith_api_key": "k"})()
    assert build_langsmith_ingest_tracer(settings) is None


def test_build_langsmith_tracer_none_when_no_key() -> None:
    settings = type("S", (), {"langsmith_enabled": True, "langsmith_api_key": ""})()
    assert build_langsmith_ingest_tracer(settings) is None


# ── Composite fan-out ────────────────────────────────────────────────────────
class _RecTracer:
    def __init__(self, name: str, log: list) -> None:
        self.name = name
        self.log = log

    def start_job(self, document_id, job_meta):
        self.log.append((self.name, "start"))
        return f"{self.name}-h"

    def span_start(self, handle, name, input_data=None, metadata=None):
        self.log.append((self.name, "span_start", handle))
        return f"{self.name}-s"

    def span_ok(self, span, output=None):
        self.log.append((self.name, "span_ok", span))

    def span_error(self, span, error):
        self.log.append((self.name, "span_error", span))

    def generation(self, handle, **kwargs):
        self.log.append((self.name, "generation", handle))

    async def finish_job(self, handle, status, output):
        self.log.append((self.name, "finish", handle, status))


@pytest.mark.asyncio
async def test_composite_fans_out_to_all_backends_with_paired_handles() -> None:
    log: list = []
    a, b = _RecTracer("a", log), _RecTracer("b", log)
    composite = CompositeIngestTracer([a, b])

    trace = composite.start_job("doc", {"attempt": 0})
    span = composite.span_start(trace, "chunk", {"chars": 5})
    composite.span_ok(span, {"num_chunks": 2})
    await composite.finish_job(trace, "COMPLETED", {"chunk_count": 2})

    # span_start nhận đúng handle per-backend (a-h cho a, b-h cho b).
    assert ("a", "span_start", "a-h") in log
    assert ("b", "span_start", "b-h") in log
    assert ("a", "span_ok", "a-s") in log
    assert ("b", "span_ok", "b-s") in log
    assert ("a", "finish", "a-h", "COMPLETED") in log
    assert ("b", "finish", "b-h", "COMPLETED") in log
