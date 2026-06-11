"""
LangSmith observability wiring — LOW-LEVEL client (RunTree, KHÔNG callback handler).

Chạy SONG SONG với langfuse_tracing (xem tracing.py CompositeTracer): cùng interface
start()/finish(), handle opaque -> orchestration KHÔNG cần biết có mấy backend.

Dùng thẳng langsmith RunTree (KHÔNG import langchain) cho khớp triết lý langfuse:
tạo root run `rag-query` (run_type=chain) + 1 child `llm` (run_type=llm, có usage + cost
tự tính qua PriceCatalog). Mọi call bọc try/except -> tracing best-effort, langsmith chết
= no-op, KHÔNG bao giờ làm vỡ/treo query.

Cost: gpt-5.4-mini có thể KHÔNG có trong bảng giá nội bộ của LangSmith -> ta tự tính qua
PriceCatalog (dataset OpenRouter) y như langfuse rồi nhét vào metadata của child run
(prompt_cost/completion_cost/total_cost) để thấy trên UI. ls_model_name set để LangSmith
tự tính nếu nó có giá.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from app.infrastructure.observability.price_catalog import PriceCatalog, load_price_catalog

logger = logging.getLogger(__name__)


class _LSTraceHandle:
    """State per-request (tạo mới mỗi query nên an toàn concurrency)."""

    __slots__ = ("run", "start_dt", "question")

    def __init__(self, run: Any, start_dt: datetime, question: str) -> None:
        self.run = run
        self.start_dt = start_dt
        self.question = question


class LangSmithTracer:
    """Best-effort wrapper quanh langsmith RunTree. Mọi lỗi đều nuốt."""

    def __init__(self, client: Any, project: str, price_catalog: PriceCatalog | None = None) -> None:
        self._client = client
        self._project = project
        self._prices = price_catalog

    def start(self, question: str, user: Any, session_id: str | None) -> _LSTraceHandle | None:
        """Tạo 1 root run cho 1 lượt query. None nếu lỗi (query vẫn chạy bình thường)."""
        try:
            from langsmith.run_trees import RunTree  # type: ignore[import]

            metadata: dict[str, Any] = {"role": getattr(user, "role", None)}
            uid = getattr(user, "id", None)
            if uid is not None:
                metadata["user_id"] = uid
            # session_id: LangSmith gom hội thoại theo metadata thread/session.
            if session_id:
                metadata["session_id"] = session_id

            # Smoke CI (header X-CI-Smoke -> session_id='ci-smoke') ghi sang PROJECT RIÊNG
            # `{project}-ci-smoke` -> deploy kế xóa nguyên project đó (delete_project), KHÔNG
            # đụng trace user thật trong `rag-query`. Mirror cơ chế session ci-smoke của langfuse.
            project = f"{self._project}-ci-smoke" if session_id == "ci-smoke" else self._project

            run = RunTree(
                name="rag-query",
                run_type="chain",
                inputs={"question": question},
                project_name=project,
                client=self._client,
                extra={"metadata": metadata},
            )
            run.post()  # tạo run ngay; patch() ở finish để cập nhật outputs/end_time
            return _LSTraceHandle(run, datetime.now(timezone.utc), question)
        except Exception as exc:  # noqa: BLE001 — tracing không được phép làm vỡ query
            logger.warning("langsmith_trace_start_failed", extra={"error": str(exc)[:200]})
            return None

    def _build_child_metadata(self, usage_meta: dict) -> dict:
        """ls_model_name (để LangSmith tự tính) + cost tự tính (USD) qua PriceCatalog."""
        input_tokens = int(usage_meta.get("input_tokens", 0) or 0)
        output_tokens = int(usage_meta.get("output_tokens", 0) or 0)
        cached_tokens = int(usage_meta.get("cached_tokens", 0) or 0)
        model = usage_meta.get("model")
        metadata: dict[str, Any] = {
            "ls_model_name": model,
            "ls_provider": "openai",
            "usage_metadata": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        }
        if self._prices is not None:
            cost = self._prices.cost(model, input_tokens, output_tokens, cached_tokens)
            if cost:
                # input_cost / output_cost / total_cost -> hiện trên UI dưới dạng metadata.
                metadata.update(cost)
        return metadata

    def finish(
        self,
        handle: _LSTraceHandle | None,
        done_event: dict | None,
        usage_meta: dict | None,
    ) -> None:
        """Ghi outcome/sources vào root run + 1 child llm (usage/cost/latency) rồi flush."""
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

            if usage_meta and usage_meta.get("model"):
                child = handle.run.create_child(
                    name="llm",
                    run_type="llm",
                    inputs={"question": handle.question},
                    start_time=handle.start_dt,
                    extra={"metadata": self._build_child_metadata(usage_meta)},
                )
                child.end(outputs=output, end_time=end_dt)
                child.post()

            handle.run.end(outputs=output, end_time=end_dt)
            handle.run.patch()  # đẩy outputs/end_time của root run

            # Đảm bảo mọi run đã được gửi (LangSmith client gửi nền theo batch).
            flush = getattr(self._client, "flush", None)
            if callable(flush):
                flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning("langsmith_trace_finish_failed", extra={"error": str(exc)[:200]})


def build_langsmith_tracer(settings: Any) -> LangSmithTracer | None:
    """
    Build LangSmithTracer khi 'langsmith' nằm trong observability backends + có API key,
    ngược lại None (observability langsmith tắt -> orchestration bỏ qua).
    """
    if "langsmith" not in settings.observability_backends:
        return None

    api_key = (settings.langsmith_api_key or "").strip()
    if not api_key:
        return None

    try:
        from langsmith import Client  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "langsmith required when OBSERVABILITY_MODE chứa 'langsmith' — xem requirements.txt"
        ) from exc

    client = Client(api_key=api_key, api_url=settings.langsmith_endpoint)

    price_catalog: PriceCatalog | None = None
    if getattr(settings, "model_price_enabled", False):
        price_catalog = load_price_catalog(
            path=settings.model_price_path,
            override_path=settings.model_price_override_path,
        )

    return LangSmithTracer(client, project=settings.langsmith_project, price_catalog=price_catalog)
