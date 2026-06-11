from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import random
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class _TraceHandle:
    document_id: str
    job_meta: dict[str, Any]
    sampled: bool
    trace: Any | None = None


@dataclass
class _SpanHandle:
    trace_handle: _TraceHandle
    name: str
    input_data: Any = None
    metadata: dict[str, Any] | None = None
    span: Any | None = None
    start_time: datetime | None = None


class IngestTracer:
    """Best-effort Langfuse wrapper for ingest jobs."""

    def __init__(
        self,
        client: Any,
        *,
        sample_rate: float = 0.0,
        trace_on_error: bool = True,
    ) -> None:
        self._client = client
        self._sample_rate = max(0.0, min(1.0, float(sample_rate)))
        self._trace_on_error = bool(trace_on_error)

    def start_job(self, document_id: str, job_meta: dict[str, Any]) -> _TraceHandle | None:
        forced = self._trace_on_error and int(job_meta.get("attempt", 0) or 0) > 0
        sampled = forced or random.random() < self._sample_rate
        handle = _TraceHandle(document_id=document_id, job_meta=dict(job_meta), sampled=sampled)
        if sampled:
            self._ensure_trace(handle)
        return handle

    def span_start(
        self,
        trace: _TraceHandle | None,
        name: str,
        input_data: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> _SpanHandle | None:
        if trace is None:
            return None
        handle = _SpanHandle(
            trace_handle=trace,
            name=name,
            input_data=input_data,
            metadata=metadata or {},
            start_time=datetime.now(timezone.utc),
        )
        if not trace.sampled:
            return handle
        trace_obj = self._ensure_trace(trace)
        if trace_obj is None:
            return handle
        try:
            handle.span = trace_obj.span(
                name=name,
                start_time=handle.start_time,
                input=input_data,
                metadata=handle.metadata,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "langfuse_span_start_failed",
                extra={"name": name, "error": str(exc)[:200]},
            )
        return handle

    def span_ok(self, span: _SpanHandle | None, output: Any = None) -> None:
        self._end_span(span, output=output, level=None)

    def span_error(self, span: _SpanHandle | None, error: BaseException) -> None:
        if span is not None and span.span is None and self._trace_on_error:
            trace_obj = self._ensure_trace(span.trace_handle)
            if trace_obj is not None:
                try:
                    span.span = trace_obj.span(
                        name=span.name,
                        start_time=span.start_time or datetime.now(timezone.utc),
                        input=span.input_data,
                        metadata=span.metadata or {},
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "langfuse_span_promote_failed",
                        extra={"name": span.name, "error": str(exc)[:200]},
                    )
        self._end_span(
            span,
            output={"error": str(error)[:500]},
            level="ERROR",
        )

    def _end_span(
        self,
        span: _SpanHandle | None,
        *,
        output: Any,
        level: str | None,
    ) -> None:
        if span is None or span.span is None:
            return
        try:
            kwargs: dict[str, Any] = {
                "output": output,
                "end_time": datetime.now(timezone.utc),
            }
            if level is not None:
                kwargs["level"] = level
            span.span.end(**kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("langfuse_span_end_failed", extra={"error": str(exc)[:200]})

    def generation(
        self,
        trace: _TraceHandle | None,
        *,
        name: str,
        model: str,
        start_time: datetime,
        input_data: Any,
        output: Any,
        metadata: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
    ) -> None:
        if trace is None or not trace.sampled:
            return
        trace_obj = self._ensure_trace(trace)
        if trace_obj is None:
            return
        try:
            kwargs: dict[str, Any] = {
                "name": name,
                "model": model,
                "start_time": start_time,
                "end_time": datetime.now(timezone.utc),
                "input": input_data,
                "output": output,
                "metadata": metadata or {},
            }
            if usage:
                kwargs["usage"] = usage
            trace_obj.generation(**kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "langfuse_generation_failed",
                extra={"name": name, "error": str(exc)[:200]},
            )

    async def finish_job(
        self,
        trace: _TraceHandle | None,
        status: str,
        output: dict[str, Any],
    ) -> None:
        if trace is None:
            return
        trace_obj = trace.trace
        if trace_obj is None and status.upper() == "FAILED" and self._trace_on_error:
            trace_obj = self._ensure_trace(trace)
        if trace_obj is None:
            return
        try:
            trace_obj.update(output={"status": status, **output})
            await asyncio.to_thread(self._client.flush)
        except Exception as exc:  # noqa: BLE001
            logger.warning("langfuse_trace_finish_failed", extra={"error": str(exc)[:200]})

    def _ensure_trace(self, handle: _TraceHandle) -> Any | None:
        if handle.trace is not None:
            return handle.trace
        try:
            handle.trace = self._client.trace(
                name="doc-ingest",
                session_id=handle.document_id,
                input={
                    "uri": handle.job_meta.get("uri"),
                    "mime": handle.job_meta.get("mime"),
                    "source_uri": handle.job_meta.get("source_uri"),
                },
                metadata={
                    "job_id": handle.job_meta.get("job_id"),
                    "attempt": handle.job_meta.get("attempt"),
                    "collection": handle.job_meta.get("collection"),
                    "correlation_id": handle.job_meta.get("correlation_id"),
                },
            )
            return handle.trace
        except Exception as exc:  # noqa: BLE001
            logger.warning("langfuse_trace_start_failed", extra={"error": str(exc)[:200]})
            return None


def build_ingest_tracer(settings: Any) -> IngestTracer | None:
    if not getattr(settings, "langfuse_enabled", False):
        return None
    public_key = (getattr(settings, "langfuse_public_key", "") or "").strip()
    secret_key = (getattr(settings, "langfuse_secret_key", "") or "").strip()
    if not public_key or not secret_key:
        return None
    try:
        from langfuse import Langfuse  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "langfuse (v2, <3) required when LANGFUSE_ENABLED=1"
        ) from exc
    return IngestTracer(
        Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=getattr(settings, "langfuse_host", "http://langfuse-web:3000"),
        ),
        sample_rate=float(getattr(settings, "langfuse_sample_rate", 0.0) or 0.0),
        trace_on_error=bool(getattr(settings, "langfuse_trace_on_error", True)),
    )
