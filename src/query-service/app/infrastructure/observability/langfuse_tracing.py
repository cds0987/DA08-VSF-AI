"""
Langfuse observability wiring — LOW-LEVEL client (KHÔNG dùng LangchainCallbackHandler).

Server self-host = langfuse v2.  CallbackHandler v2 cần `langchain` đời cũ (langchain-core
<1.0) trong khi query-service chạy langchain-core 1.x → hạ cấp core → crash giữa stream.
Nên ở đây dùng thẳng low-level client `langfuse.Langfuse` (KHÔNG import langchain): tạo
trace + 1 generation (cost/latency) + flush.  Mọi call bọc try/except → tracing là
best-effort, KHÔNG bao giờ làm hỏng/treo query (langfuse chết = no-op).

Cost: Langfuse self-host v2 KHÔNG có pricing model mới → ta tự tính qua PriceCatalog
(dataset OpenRouter) rồi gửi thẳng input_cost/output_cost/total_cost vào generation.
Latency: generation phải có start_time/end_time tường minh, nếu không UI hiện ~0.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from app.infrastructure.observability.price_catalog import PriceCatalog, load_price_catalog

logger = logging.getLogger(__name__)


class _TraceHandle:
    """State per-request (an toàn với concurrency vì tạo mới mỗi query)."""

    __slots__ = ("trace", "start_dt", "question")

    def __init__(self, trace: Any, start_dt: datetime, question: str) -> None:
        self.trace = trace
        self.start_dt = start_dt
        self.question = question


class LangfuseTracer:
    """Best-effort wrapper quanh langfuse v2 low-level client. Mọi lỗi đều nuốt."""

    def __init__(self, client: Any, price_catalog: PriceCatalog | None = None) -> None:
        self._client = client
        self._prices = price_catalog

    def start(
        self,
        question: str,
        user: Any,
        session_id: str | None,
        conversation_title: str | None = None,
    ) -> _TraceHandle | None:
        """Tạo 1 trace cho 1 lượt query. Trả None nếu lỗi (query vẫn chạy bình thường)."""
        try:
            metadata: dict[str, Any] = {
                "role": getattr(user, "role", None),
                "department": getattr(user, "department", None),
            }
            if conversation_title:
                metadata["conversation_title"] = conversation_title
            trace = self._client.trace(
                name="rag-query",
                user_id=getattr(user, "id", None),
                session_id=session_id,
                input=question,
                metadata=metadata,
            )
            return _TraceHandle(trace, datetime.now(timezone.utc), question)
        except Exception as exc:  # noqa: BLE001 — tracing không được phép làm vỡ query
            logger.warning("langfuse_trace_start_failed", extra={"error": str(exc)[:200]})
            return None

    def _build_usage(self, usage_meta: dict) -> dict:
        """Gộp token + cost (USD tự tính) thành usage dict cho langfuse generation."""
        input_tokens = int(usage_meta.get("input_tokens", 0) or 0)
        output_tokens = int(usage_meta.get("output_tokens", 0) or 0)
        cached_tokens = int(usage_meta.get("cached_tokens", 0) or 0)
        usage: dict[str, Any] = {
            "input": input_tokens,
            "output": output_tokens,
            "total": input_tokens + output_tokens,
            "unit": "TOKENS",
        }
        if self._prices is not None:
            cost = self._prices.cost(
                usage_meta.get("model"), input_tokens, output_tokens, cached_tokens
            )
            if cost:
                usage.update(cost)  # input_cost / output_cost / total_cost
        return usage

    def span_start(
        self,
        handle: "_TraceHandle | None",
        name: str,
        input_data: Any = None,
        metadata: dict | None = None,
        parent: Any = None,
    ) -> Any:
        """Tạo child span. Mặc định gắn lên trace (con của root); nếu truyền `parent`
        (1 span object), tạo span LỒNG dưới parent đó (langfuse span cũng có .span()).
        Trả span object hoặc None nếu lỗi. Best-effort."""
        # parent (span object) ưu tiên; nếu không có thì gắn lên trace của handle.
        target = parent if parent is not None else (handle.trace if handle is not None else None)
        if target is None:
            return None
        try:
            return target.span(
                name=name,
                start_time=datetime.now(timezone.utc),
                input=input_data,
                metadata=metadata or {},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("langfuse_span_start_failed", extra={"name": name, "error": str(exc)[:200]})
            return None

    def span_end(self, span: Any, output_data: Any = None, level: str | None = None) -> None:
        """Đóng span với output. Best-effort."""
        if span is None:
            return
        try:
            kwargs: dict[str, Any] = {"output": output_data, "end_time": datetime.now(timezone.utc)}
            if level:
                kwargs["level"] = level
            span.end(**kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("langfuse_span_end_failed", extra={"error": str(exc)[:200]})

    def span(
        self,
        handle: _TraceHandle | None,
        name: str,
        *,
        input: Any = None,
        metadata: dict | None = None,
    ) -> Any | None:
        """Alias tương thích cho callsite cũ dùng span(...)."""
        return self.span_start(handle, name=name, input_data=input, metadata=metadata)

    def end_span(self, span: Any | None, *, output: Any = None, level: str | None = None) -> None:
        """Alias tương thích cho callsite cũ dùng end_span(...)."""
        self.span_end(span, output_data=output, level=level)

    def get_trace_id(self, handle: "_TraceHandle | None") -> str | None:
        """Trả Langfuse trace ID để dùng cho score API. None nếu không có."""
        if handle is None:
            return None
        try:
            return handle.trace.id
        except Exception:
            return None

    def score(self, trace_id: str, value: int, name: str = "user_feedback") -> None:
        """Ghi user score (1 = helpful, -1 = not helpful) lên Langfuse trace. Best-effort."""
        try:
            self._client.score(trace_id=trace_id, name=name, value=float(value))
            self._client.flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning("langfuse_score_failed", extra={"error": str(exc)[:200]})

    def finish(
        self,
        handle: _TraceHandle | None,
        done_event: dict | None,
        usage_meta: dict | None,
    ) -> None:
        """
        Ghi answer/sources/outcome vào trace + 1 generation (model, usage, cost, latency)
        rồi flush. usage_meta = {model, input_tokens, output_tokens, cached_tokens} từ
        orchestration (gom từ các AIMessage). Best-effort.
        """
        if handle is None:
            return
        try:
            ev = done_event or {}
            end_dt = datetime.now(timezone.utc)
            answer = ev.get("_answer") or ""
            sources = ev.get("sources") or []

            trace_output: dict = {
                "answer": answer,
                "outcome": ev.get("outcome"),
                "num_sources": len(sources),
                "iterations": ev.get("iterations"),
            }
            if ev.get("error"):
                trace_output["error"] = ev.get("error")
            if sources:
                trace_output["sources"] = [
                    {
                        "title": s.get("document_name", ""),
                        "score": round(float(s.get("score") or 0), 3),
                    }
                    for s in sources[:5]
                ]
            handle.trace.update(output=trace_output)

            if usage_meta and usage_meta.get("model"):
                handle.trace.generation(
                    name="llm",
                    model=usage_meta.get("model"),
                    start_time=handle.start_dt,
                    end_time=end_dt,
                    input=handle.question,
                    output=answer or trace_output,
                    usage=self._build_usage(usage_meta),
                )

            self._client.flush()  # bắt buộc — không flush thì trace chưa gửi
        except Exception as exc:  # noqa: BLE001
            logger.warning("langfuse_trace_finish_failed", extra={"error": str(exc)[:200]})


def build_langfuse_tracer(settings: Any) -> LangfuseTracer | None:
    """
    Build LangfuseTracer khi 'langfuse' nằm trong observability backends + có đủ key.

    None = backend langfuse tắt → orchestration bỏ qua (dev/test offline OK). Backend
    khác (langsmith) vẫn có thể bật song song — xem tracing.build_tracer.
    """
    if "langfuse" not in settings.observability_backends:
        return None

    public_key = (settings.langfuse_public_key or "").strip()
    secret_key = (settings.langfuse_secret_key or "").strip()
    if not public_key or not secret_key:
        return None

    try:
        # v2 low-level client — KHÔNG import langchain (tránh xung đột langchain-core 1.x).
        from langfuse import Langfuse  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "langfuse (v2, <3) required when OBSERVABILITY_MODE=langfuse — xem requirements.txt"
        ) from exc

    client = Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        host=settings.langfuse_host,
    )

    # Catalog giá tự tính cost (best-effort; rỗng -> generation vẫn có token, chỉ thiếu cost).
    price_catalog: PriceCatalog | None = None
    if getattr(settings, "model_price_enabled", False):
        price_catalog = load_price_catalog(
            path=settings.model_price_path,
            override_path=settings.model_price_override_path,
        )

    return LangfuseTracer(client, price_catalog=price_catalog)
