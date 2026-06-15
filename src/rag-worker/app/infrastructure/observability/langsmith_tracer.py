"""LangSmith observability cho luồng INGEST của rag-worker — LOW-LEVEL RunTree.

Cùng interface duck-typed với IngestTracer (langfuse): start_job / span_start /
span_ok / span_error / generation / finish_job, nên use case + engine KHÔNG cần biết
backend nào. Composite (ingest_tracing.py) fan-out cả hai khi cùng bật.

Tách biệt query-service: root run name='doc-ingest' (query dùng 'rag-query') và
project mặc định 'vsf-rag-ingest' (query dùng 'vsf-rag-chatbot') -> phân biệt rõ
luồng ingest vs query trên LangSmith.

Mọi call bọc try/except: tracing best-effort, langsmith chết = no-op, KHÔNG bao giờ
làm vỡ/treo ingest.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import random
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class _LSTrace:
    document_id: str
    job_meta: dict[str, Any]
    sampled: bool
    run: Any | None = None  # root RunTree, tạo lazily


@dataclass
class _LSSpan:
    trace: _LSTrace
    name: str
    input_data: Any = None
    start_time: datetime | None = None
    child: Any | None = None  # child RunTree, có thể tạo lazily khi lỗi


class LangSmithIngestTracer:
    """Best-effort wrapper quanh langsmith RunTree cho ingest jobs."""

    def __init__(
        self,
        client: Any,
        project: str,
        *,
        sample_rate: float = 1.0,
        trace_on_error: bool = True,
    ) -> None:
        self._client = client
        self._project = project
        self._sample_rate = max(0.0, min(1.0, float(sample_rate)))
        self._trace_on_error = bool(trace_on_error)

    # ── trace gốc cho 1 job ───────────────────────────────────────────────
    def start_job(self, document_id: str, job_meta: dict[str, Any]) -> _LSTrace | None:
        forced = self._trace_on_error and int(job_meta.get("attempt", 0) or 0) > 0
        sampled = forced or random.random() < self._sample_rate
        handle = _LSTrace(document_id=document_id, job_meta=dict(job_meta), sampled=sampled)
        if sampled:
            self._ensure_root(handle)
        return handle

    def _project_name(self, handle: _LSTrace) -> str:
        # Smoke CI (correlation_id/uri chứa 'ci-smoke') ghi sang project riêng để
        # deploy kế dọn, KHÔNG đụng trace ingest thật. Mirror cơ chế của query-service.
        meta = handle.job_meta
        marker = f"{meta.get('correlation_id', '')}{meta.get('uri', '')}"
        return f"{self._project}-ci-smoke" if "ci-smoke" in marker else self._project

    def _ensure_root(self, handle: _LSTrace) -> Any | None:
        if handle.run is not None:
            return handle.run
        try:
            from langsmith.run_trees import RunTree  # type: ignore[import]

            meta = handle.job_meta
            run = RunTree(
                name="doc-ingest",
                run_type="chain",
                inputs={
                    "uri": meta.get("uri"),
                    "mime": meta.get("mime"),
                    "source_uri": meta.get("source_uri"),
                },
                project_name=self._project_name(handle),
                client=self._client,
                extra={
                    "metadata": {
                        "document_id": handle.document_id,
                        "session_id": handle.document_id,
                        "job_id": meta.get("job_id"),
                        "attempt": meta.get("attempt"),
                        "collection": meta.get("collection"),
                        "correlation_id": meta.get("correlation_id"),
                    }
                },
            )
            run.post()
            handle.run = run
            return run
        except Exception as exc:  # noqa: BLE001 — tracing không được phép làm vỡ ingest
            logger.warning("langsmith_trace_start_failed", extra={"error": str(exc)[:200]})
            return None

    # ── span con (parse/chunk/caption/embed/qdrant-write) ─────────────────
    def span_start(
        self,
        trace: _LSTrace | None,
        name: str,
        input_data: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> _LSSpan | None:
        if trace is None:
            return None
        span = _LSSpan(
            trace=trace,
            name=name,
            input_data=input_data,
            start_time=datetime.now(timezone.utc),
        )
        # Chưa sample + không trace-on-error -> giữ no-op (không tạo child).
        if trace.sampled:
            self._open_child(span)
        return span

    def _open_child(self, span: _LSSpan) -> Any | None:
        if span.child is not None:
            return span.child
        root = self._ensure_root(span.trace)
        if root is None:
            return None
        try:
            child = root.create_child(
                name=span.name,
                run_type="tool",
                inputs=span.input_data if isinstance(span.input_data, dict) else {"input": span.input_data},
                start_time=span.start_time or datetime.now(timezone.utc),
            )
            child.post()
            span.child = child
            return child
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "langsmith_span_start_failed",
                extra={"name": span.name, "error": str(exc)[:200]},
            )
            return None

    def span_ok(self, span: _LSSpan | None, output: Any = None) -> None:
        if span is None or span.child is None:
            return
        self._end_child(span.child, outputs=_as_dict(output), error=None)

    def span_error(self, span: _LSSpan | None, error: BaseException) -> None:
        if span is None:
            return
        # Lỗi: nếu trace-on-error thì mở child kể cả khi chưa sample, để thấy điểm hỏng.
        if span.child is None and self._trace_on_error:
            self._open_child(span)
        if span.child is None:
            return
        self._end_child(span.child, outputs=None, error=str(error)[:500])

    def _end_child(self, child: Any, *, outputs: dict | None, error: str | None) -> None:
        try:
            child.end(outputs=outputs or {}, error=error, end_time=datetime.now(timezone.utc))
            child.patch()
        except Exception as exc:  # noqa: BLE001
            logger.warning("langsmith_span_end_failed", extra={"error": str(exc)[:200]})

    # ── generation (caption/embed LLM call) ───────────────────────────────
    def generation(
        self,
        trace: _LSTrace | None,
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
        root = self._ensure_root(trace)
        if root is None:
            return
        try:
            child_meta: dict[str, Any] = {"ls_model_name": model, "ls_provider": "openai"}
            if metadata:
                child_meta.update(metadata)
            if usage:
                child_meta["usage_metadata"] = usage
            child = root.create_child(
                name=name,
                run_type="llm",
                inputs=_as_dict(input_data),
                start_time=start_time,
                extra={"metadata": child_meta},
            )
            child.end(outputs=_as_dict(output), end_time=datetime.now(timezone.utc))
            child.post()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "langsmith_generation_failed",
                extra={"name": name, "error": str(exc)[:200]},
            )

    # ── kết thúc job ──────────────────────────────────────────────────────
    async def finish_job(
        self,
        trace: _LSTrace | None,
        status: str,
        output: dict[str, Any],
    ) -> None:
        if trace is None:
            return
        run = trace.run
        if run is None and status.upper() in {"FAILED", "LEASE_LOST"} and self._trace_on_error:
            run = self._ensure_root(trace)
        if run is None:
            return
        try:
            run.end(outputs={"status": status, **output}, end_time=datetime.now(timezone.utc))
            run.patch()
            flush = getattr(self._client, "flush", None)
            if callable(flush):
                await asyncio.to_thread(flush)
        except Exception as exc:  # noqa: BLE001
            logger.warning("langsmith_trace_finish_failed", extra={"error": str(exc)[:200]})


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {"value": value}


def build_langsmith_ingest_tracer(settings: Any) -> LangSmithIngestTracer | None:
    """Build khi LANGSMITH_ENABLED=1 + có API key, ngược lại None (tự bỏ qua)."""
    if not getattr(settings, "langsmith_enabled", False):
        return None
    api_key = (getattr(settings, "langsmith_api_key", "") or "").strip()
    if not api_key:
        return None
    try:
        from langsmith import Client  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "langsmith required when LANGSMITH_ENABLED=1 — xem requirements.txt"
        ) from exc
    client = Client(
        api_key=api_key,
        api_url=getattr(settings, "langsmith_endpoint", "https://api.smith.langchain.com"),
    )
    return LangSmithIngestTracer(
        client,
        project=getattr(settings, "langsmith_project", "vsf-rag-ingest"),
        sample_rate=float(getattr(settings, "langsmith_sample_rate", 1.0) or 1.0),
        trace_on_error=bool(getattr(settings, "langsmith_trace_on_error", True)),
    )
