"""
Langfuse observability wiring.

Returns a LangChain CallbackHandler when OBSERVABILITY_MODE=langfuse and keys are
configured, otherwise returns None.  LangGraph forwards LangChain callbacks natively,
so passing the handler in the run config is sufficient to capture all node/LLM/tool spans.
"""
from __future__ import annotations

from typing import Any


def build_langfuse_callback(settings: Any) -> Any | None:
    """
    Build and return a Langfuse LangChain CallbackHandler, or None when disabled.

    Args:
        settings: app.infrastructure.config.Settings instance.

    Returns:
        langfuse.langchain.CallbackHandler if observability_mode=langfuse and keys present,
        otherwise None (no-op — dev/test stays fully offline).
    """
    if settings.observability_mode.strip().lower() != "langfuse":
        return None

    public_key = (settings.langfuse_public_key or "").strip()
    secret_key = (settings.langfuse_secret_key or "").strip()
    if not public_key or not secret_key:
        return None

    try:
        # Langfuse server self-host = v2 -> dùng SDK v2 path `langfuse.callback`
        # (KHÔNG phải `langfuse.langchain` của v3/v4 — server v2 không nhận OTLP).
        from langfuse.callback import CallbackHandler  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "langfuse v2 + langchain required when OBSERVABILITY_MODE=langfuse — xem requirements.txt"
        ) from exc

    return CallbackHandler(
        public_key=public_key,
        secret_key=secret_key,
        host=settings.langfuse_host,
    )
