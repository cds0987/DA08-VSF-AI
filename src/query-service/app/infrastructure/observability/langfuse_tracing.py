"""
Langfuse observability wiring — LOW-LEVEL client (KHÔNG dùng LangchainCallbackHandler).

Server self-host = langfuse v2.  CallbackHandler v2 cần `langchain` đời cũ (langchain-core
<1.0) trong khi query-service chạy langchain-core 1.x → hạ cấp core → crash giữa stream.
Nên ở đây dùng thẳng low-level client `langfuse.Langfuse` (KHÔNG import langchain): tạo
trace + update output + flush.  Mọi call bọc try/except → tracing là best-effort, KHÔNG
bao giờ làm hỏng/treo query (langfuse chết = no-op).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class LangfuseTracer:
    """Best-effort wrapper quanh langfuse v2 low-level client. Mọi lỗi đều nuốt."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def start(self, question: str, user: Any, session_id: str | None) -> Any | None:
        """Tạo 1 trace cho 1 lượt query. Trả None nếu lỗi (query vẫn chạy bình thường)."""
        try:
            return self._client.trace(
                name="rag-query",
                user_id=getattr(user, "id", None),
                session_id=session_id,
                input=question,
                metadata={"role": getattr(user, "role", None)},
            )
        except Exception as exc:  # noqa: BLE001 — tracing không được phép làm vỡ query
            logger.warning("langfuse_trace_start_failed", extra={"error": str(exc)[:200]})
            return None

    def finish(self, trace: Any, done_event: dict | None) -> None:
        """Ghi outcome/sources từ event 'done' vào trace rồi flush. Best-effort."""
        if trace is None:
            return
        try:
            ev = done_event or {}
            trace.update(
                output={
                    "outcome": ev.get("outcome"),
                    "num_sources": len(ev.get("sources") or []),
                    "iterations": ev.get("iterations"),
                    "error": ev.get("error"),
                }
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
    return LangfuseTracer(client)
