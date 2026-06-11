from __future__ import annotations

import pytest

from app.infrastructure.observability.langfuse_tracer import IngestTracer, build_ingest_tracer


class _DummySpan:
    def __init__(self, name: str, events: list[str]) -> None:
        self._name = name
        self._events = events

    def end(self, **kwargs) -> None:
        self._events.append(f"end:{self._name}:{kwargs.get('level', 'OK')}")


class _DummyTrace:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def span(self, *, name, start_time, input, metadata):
        self._events.append(f"span:{name}")
        return _DummySpan(name, self._events)

    def generation(self, **kwargs) -> None:
        self._events.append(f"generation:{kwargs['name']}")

    def update(self, **kwargs) -> None:
        self._events.append(f"update:{kwargs['output']['status']}")


class _DummyClient:
    def __init__(self) -> None:
        self.events: list[str] = []

    def trace(self, **kwargs):
        self.events.append(f"trace:{kwargs['session_id']}")
        return _DummyTrace(self.events)

    def flush(self) -> None:
        self.events.append("flush")


@pytest.mark.asyncio
async def test_ingest_tracer_promotes_unsampled_failure_to_trace() -> None:
    client = _DummyClient()
    tracer = IngestTracer(client, sample_rate=0.0, trace_on_error=True)

    trace = tracer.start_job("doc-1", {"attempt": 0, "uri": "s3://a", "mime": "pdf"})
    span = tracer.span_start(trace, "parse", {"uri": "s3://a"})
    tracer.span_error(span, RuntimeError("boom"))
    await tracer.finish_job(trace, "FAILED", {"stage": "parse"})

    assert client.events == [
        "trace:doc-1",
        "span:parse",
        "end:parse:ERROR",
        "update:FAILED",
        "flush",
    ]


def test_ingest_tracer_forces_retry_jobs() -> None:
    client = _DummyClient()
    tracer = IngestTracer(client, sample_rate=0.0, trace_on_error=True)

    tracer.start_job("doc-retry", {"attempt": 2, "uri": "s3://a", "mime": "pdf"})

    assert client.events == ["trace:doc-retry"]


def test_build_ingest_tracer_returns_none_when_disabled() -> None:
    settings = type(
        "Settings",
        (),
        {
            "langfuse_enabled": False,
            "langfuse_public_key": "",
            "langfuse_secret_key": "",
            "langfuse_host": "http://langfuse-web:3000",
            "langfuse_sample_rate": 0.0,
            "langfuse_trace_on_error": True,
        },
    )()

    assert build_ingest_tracer(settings) is None
