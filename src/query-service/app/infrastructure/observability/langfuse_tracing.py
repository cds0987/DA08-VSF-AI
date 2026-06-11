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

    def start(self, question: str, user: Any, session_id: str | None) -> _TraceHandle | None:
        """Tạo 1 trace cho 1 lượt query. Trả None nếu lỗi (query vẫn chạy bình thường)."""
        try:
            trace = self._client.trace(
                name="rag-query",
                user_id=getattr(user, "id", None),
                session_id=session_id,
                input=question,
                metadata={"role": getattr(user, "role", None)},
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

    def finish(
        self,
        handle: _TraceHandle | None,
        done_event: dict | None,
        usage_meta: dict | None,
    ) -> None:
        """
        Ghi outcome/sources vào trace + 1 generation (model, usage, cost, latency) rồi
        flush. usage_meta = {model, input_tokens, output_tokens, cached_tokens} từ
        orchestration (gom từ các AIMessage). Best-effort.
        """
        if handle is None:
            return
        try:
            ev = done_event or {}
            end_dt = datetime.now(timezone.utc)
            output = {
                "outcome": ev.get("outcome"),
                "num_sources": len(ev.get("sources") or []),
                "iterations": ev.get("iterations"),
                "error": ev.get("error"),
            }
            handle.trace.update(output=output)

            if usage_meta and usage_meta.get("model"):
                handle.trace.generation(
                    name="llm",
                    model=usage_meta.get("model"),
                    start_time=handle.start_dt,
                    end_time=end_dt,
                    input=handle.question,
                    output=output,
                    usage=self._build_usage(usage_meta),
                )

            self._client.flush()  # bắt buộc — không flush thì trace chưa gửi
        except Exception as exc:  # noqa: BLE001
            logger.warning("langfuse_trace_finish_failed", extra={"error": str(exc)[:200]})


def build_langfuse_tracer(settings: Any) -> LangfuseTracer | None:
    """
    Build LangfuseTracer khi OBSERVABILITY_MODE=langfuse và có đủ key, ngược lại None.

    None = observability tắt → orchestration bỏ qua hoàn toàn (dev/test offline OK).
    """
    if settings.observability_mode.strip().lower() != "langfuse":
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
