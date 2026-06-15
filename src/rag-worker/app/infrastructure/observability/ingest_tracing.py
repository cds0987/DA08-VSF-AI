"""Builder hợp nhất tracer ingest: Langfuse + LangSmith (composite fan-out).

runtime.py gọi build_ingest_tracer(settings) (export qua package __init__). Backend
nào có cấu hình + key thì bật; cả hai bật -> CompositeIngestTracer fan-out song song.
Không backend nào -> None (ingest chạy bình thường, không trace).

Handle (trace/span) là opaque với use case + engine: composite bọc danh sách handle
per-backend và fan-out từng method theo đúng interface IngestTracer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.infrastructure.observability.langfuse_tracer import build_ingest_tracer as _build_langfuse
from app.infrastructure.observability.langsmith_tracer import build_langsmith_ingest_tracer


@dataclass
class _CompositeTrace:
    handles: list[Any]


@dataclass
class _CompositeSpan:
    spans: list[Any]


class CompositeIngestTracer:
    """Fan-out mọi call tracing sang nhiều backend. Handle = list per-backend."""

    def __init__(self, tracers: list[Any]) -> None:
        self._tracers = tracers

    def start_job(self, document_id: str, job_meta: dict[str, Any]) -> _CompositeTrace:
        return _CompositeTrace([t.start_job(document_id, job_meta) for t in self._tracers])

    def span_start(
        self,
        trace: _CompositeTrace | None,
        name: str,
        input_data: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> _CompositeSpan | None:
        if trace is None:
            return None
        return _CompositeSpan(
            [
                t.span_start(h, name, input_data, metadata)
                for t, h in zip(self._tracers, trace.handles)
            ]
        )

    def span_ok(self, span: _CompositeSpan | None, output: Any = None) -> None:
        if span is None:
            return
        for t, s in zip(self._tracers, span.spans):
            t.span_ok(s, output)

    def span_error(self, span: _CompositeSpan | None, error: BaseException) -> None:
        if span is None:
            return
        for t, s in zip(self._tracers, span.spans):
            t.span_error(s, error)

    def generation(
        self,
        trace: _CompositeTrace | None,
        *,
        name: str,
        model: str,
        start_time: datetime,
        input_data: Any,
        output: Any,
        metadata: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
    ) -> None:
        if trace is None:
            return
        for t, h in zip(self._tracers, trace.handles):
            t.generation(
                h,
                name=name,
                model=model,
                start_time=start_time,
                input_data=input_data,
                output=output,
                metadata=metadata,
                usage=usage,
            )

    async def finish_job(
        self,
        trace: _CompositeTrace | None,
        status: str,
        output: dict[str, Any],
    ) -> None:
        if trace is None:
            return
        for t, h in zip(self._tracers, trace.handles):
            await t.finish_job(h, status, output)


def build_ingest_tracer(settings: Any) -> Any | None:
    """Dựng tracer ingest từ các backend đang bật. None nếu không backend nào."""
    tracers = [
        tracer
        for tracer in (_build_langfuse(settings), build_langsmith_ingest_tracer(settings))
        if tracer is not None
    ]
    if not tracers:
        return None
    if len(tracers) == 1:
        return tracers[0]
    return CompositeIngestTracer(tracers)
