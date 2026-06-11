"""
Observability tracer dựng từ OBSERVABILITY_MODE — gộp nhiều backend song song.

OBSERVABILITY_MODE nhận danh sách (phẩy/chấm phẩy): "langfuse", "langsmith",
"langfuse,langsmith", "off". build_tracer dựng từng backend (best-effort, thiếu key ->
bỏ qua backend đó) rồi:
  - 0 backend  -> None  (orchestration bỏ qua tracing hoàn toàn)
  - 1 backend  -> chính tracer đó (không bọc thừa)
  - 2+ backend -> CompositeTracer fan-out

CompositeTracer giữ interface start()/finish() y hệt tracer đơn; handle của nó là list
(child_tracer, child_handle) — orchestration truyền lại nguyên vẹn nên KHÔNG cần sửa.
"""
from __future__ import annotations

import logging
from typing import Any

from app.infrastructure.observability.langfuse_tracing import build_langfuse_tracer
from app.infrastructure.observability.langsmith_tracing import build_langsmith_tracer

logger = logging.getLogger(__name__)


class CompositeTracer:
    """Fan-out tới nhiều tracer con. Mỗi con đã tự best-effort; ở đây bọc thêm 1 lớp."""

    def __init__(self, tracers: list[Any]) -> None:
        self._tracers = tracers

    def start(self, question: str, user: Any, session_id: str | None) -> list | None:
        handles = []
        for tracer in self._tracers:
            try:
                handles.append((tracer, tracer.start(question, user, session_id)))
            except Exception as exc:  # noqa: BLE001 — 1 backend lỗi không kéo theo cái khác
                logger.warning("composite_trace_start_failed", extra={"error": str(exc)[:200]})
        return handles or None

    def finish(self, handle: list | None, done_event: dict | None, usage_meta: dict | None) -> None:
        if not handle:
            return
        for tracer, child_handle in handle:
            try:
                tracer.finish(child_handle, done_event, usage_meta)
            except Exception as exc:  # noqa: BLE001
                logger.warning("composite_trace_finish_failed", extra={"error": str(exc)[:200]})


def build_tracer(settings: Any) -> Any | None:
    """Dựng tracer hợp nhất từ các backend đang bật. None nếu không backend nào."""
    tracers: list[Any] = []
    for build in (build_langfuse_tracer, build_langsmith_tracer):
        tracer = build(settings)
        if tracer is not None:
            tracers.append(tracer)

    if not tracers:
        return None
    if len(tracers) == 1:
        return tracers[0]
    return CompositeTracer(tracers)
